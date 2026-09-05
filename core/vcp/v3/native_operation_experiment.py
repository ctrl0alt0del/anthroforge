"""Isolated heterogeneous native-operation scheduler experiment for Fiber V3."""

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from ctypes import POINTER, Structure, byref, c_double, c_int, c_int64, c_void_p, cast, pointer
from dataclasses import dataclass
import hashlib
from pathlib import Path
from threading import Condition, Event
from time import perf_counter

import numpy as np

from ..v2 import collision_native as cn
from ..v2.collision import (V2NativeSweepSession, clear_native_collision_world_cache,
                            clear_triangle_snapshot_cache)


EXPERIMENT_DLL = Path(__file__).resolve().parents[3] / "native/fiber_ccd/af_fiber_ccd_v3_ops_experiment.dll"
MEASURE, STRUCTURAL, SWEEP = 1, 2, 3


class _MeasurePayload(Structure):
    _fields_ = [("session", c_void_p), ("points", POINTER(c_double))]
    _fields_ += [(name, c_double) for name in ("span", "activation", "threshold")]
    _fields_ += [("output", POINTER(cn._NativeContactPair)), ("capacity", c_int), ("code", c_int)]
    _fields_ += [("contacts", cn._NativeWorldContacts), ("clear", POINTER(c_int))]
    _fields_ += [("blockers", POINTER(c_int)), ("minima", POINTER(c_double)),
                 ("validation", cn._NativeWorldBatch)]


class _StructuralPayload(Structure):
    _fields_ = [("session", c_void_p)]
    _fields_ += [(name, POINTER(c_double)) for name in ("d", "l1", "l2", "rhs")]
    _fields_ += [("edges", POINTER(c_int64)), ("factors", POINTER(c_double)),
                 ("normals", POINTER(c_double)), ("contacts", c_int),
                 ("pins", POINTER(c_int64)), ("targets", POINTER(c_double))]
    _fields_ += [(name, c_int) for name in ("pin_count", "count")]
    _fields_ += [("base", POINTER(c_double)), ("responses", POINTER(c_double)),
                 ("result", cn._NativeBlockResult)]


class _OperationDescriptor(Structure):
    _fields_ = [(name, c_int) for name in ("kind", "status", "worker", "ordinal")]
    _fields_ += [("elapsed_ms", c_double), ("payload", c_void_p)]


class _OperationStats(Structure):
    _fields_ = [(name, c_int) for name in
                ("submitted", "completed", "workers", "workers_used", "measures", "structurals", "sweeps")]
    _fields_ += [("elapsed_ms", c_double)]


class _CoordinatorStats(Structure):
    _fields_ = [(name, c_int) for name in ("operations", "streams", "contact_jobs",
        "validation_jobs", "structural_jobs", "ccd_broad_jobs", "ccd_pair_jobs",
        "workers", "workers_used", "deterministic")]
    _fields_ += [("elapsed_ms", c_double)]


@dataclass(frozen=True)
class V3OperationReport:
    elapsed_ms: float
    waves: int
    jobs: int
    workers_used: int
    measures: int
    structurals: int
    sweeps: int


@dataclass(frozen=True)
class V3CoordinatorReport:
    operations: int
    streams: int
    contact_jobs: int
    validation_jobs: int
    structural_jobs: int
    ccd_broad_jobs: int
    ccd_pair_jobs: int
    workers: int
    workers_used: int
    deterministic: bool
    elapsed_ms: float


@dataclass(frozen=True)
class V3CoordinatorReplayReport:
    coordinator: object
    operations: int
    exact_operations: int
    contact_mismatches: int
    structural_mismatches: int
    sweep_mismatches: int
    maximum_safe_delta: float
    more_permissive_sweeps: int
    valid_mismatches: int
    baseline_validation_failures: int
    static_validation_failures: int


class _Operation:
    def __init__(self, kind, session, payload, references):
        self.kind, self.session, self.payload = int(kind), session, payload
        self.references, self.done = tuple(references), False
        self.worker, self.elapsed_ms, self.status = -1, 0.0, 0

    def descriptor(self, ordinal):
        address = cast(pointer(self.payload), c_void_p)
        return _OperationDescriptor(self.kind, -1, -1, int(ordinal), 0.0, address)

    def accept(self, row):
        self.status, self.worker = int(row.status), int(row.worker)
        self.elapsed_ms, self.done = float(row.elapsed_ms), True


@dataclass
class _PendingCall:
    operation: object
    event: object = None
    error: object = None

    def __post_init__(self):
        self.event = Event()


class _MeasureOperation(_Operation):
    def __init__(self, session, points, span, activation, threshold):
        low = session.native; values = cn._v3_points(points, low.edge_count)
        capacity = max(1, low._contact_capacity); rows = (cn._NativeContactPair * capacity)()
        arrays = cn._validation_arrays(low.edge_count); payload = _measure_payload(low, values, rows, arrays,
                                                                                   span, activation, threshold)
        super().__init__(MEASURE, session, payload, (values, rows, arrays))

    def result(self):
        low = self.session.native; rows = self.references[1]; arrays = self.references[2]
        values = low._contact_rows(rows, self.payload.code, self.payload.contacts.active)
        low._check_contact_code(self.payload.code)
        return (self.session._contacts(values, self.payload.contacts),
                self.session._validation(arrays, self.payload.validation))


class _StructuralOperation(_Operation):
    def __init__(self, session, base, rhs, contacts, pins, targets):
        low = session.native; count = low.edge_count + 1
        bands = tuple(cn._scalar_band(value, count) for value in base)
        values, arrays = np.ascontiguousarray(rhs, dtype=np.float64), cn._response_arrays(contacts)
        pin_rows = np.ascontiguousarray(pins, dtype=np.int64)
        pin_values = np.ascontiguousarray(targets, dtype=np.float64)
        output, responses = np.empty_like(values), np.empty((len(arrays[0]), count, 3))
        payload = _structural_payload(low, bands, values, arrays, pin_rows, pin_values, output, responses, count)
        super().__init__(STRUCTURAL, session, payload,
                         (*bands, values, *arrays, pin_rows, pin_values, output, responses))

    def result(self):
        if not self.payload.result.valid: raise np.linalg.LinAlgError("native V3 structural responses failed")
        return self.references[-2], self.references[-1], cn._block_result(self.payload.result)


class _SweepOperation(_Operation):
    def __init__(self, session, source, target, clearance, tolerance, budget):
        inputs = session.native.batch_sweep_input(source, target, clearance, tolerance, budget)
        payload, _low = cn._v3_batch_row(inputs)
        super().__init__(SWEEP, session, payload, payload._arrays)

    def result(self):
        values = (self.payload.candidates, self.payload.pairs, self.payload.edge, self.payload.face)
        return self.session._safe_step_result(self.payload.result, values)


class V3OperationSessionProxy:
    def __init__(self, session, broker):
        self._session, self.native, self.world = session, session.native, session.world
        self.broker = broker

    @property
    def snapshot_attached(self):
        return self._session.snapshot_attached

    def _defer(self, kind, factory, direct):
        if not self.broker.shared(): return direct()
        operation = factory()
        if operation.kind != kind: raise RuntimeError("invalid V3 operation kind")
        return self.broker.submit(operation)

    def measure(self, points, span, activation, threshold):
        factory = lambda: _MeasureOperation(self._session, points, span, activation, threshold)
        direct = lambda: self._session.measure(points, span, activation, threshold)
        return self._defer(MEASURE, factory, direct)

    def structural_responses(self, base, rhs, contacts, pins, targets):
        factory = lambda: _StructuralOperation(self._session, base, rhs, contacts, pins, targets)
        direct = lambda: self._session.structural_responses(base, rhs, contacts, pins, targets)
        return self._defer(STRUCTURAL, factory, direct)

    def safe_step(self, source, target, clearance, tolerance=1.0e-5, budget=262143):
        if not self.snapshot_attached: return self._session._clear_step()
        factory = lambda: _SweepOperation(self._session, source, target, clearance, tolerance, budget)
        direct = lambda: self._session.safe_step(source, target, clearance, tolerance, budget)
        return self._defer(SWEEP, factory, direct)

    def begin_sweep(self, source, target, clearance, tolerance=1.0e-5, budget=262143):
        value = V2NativeSweepSession(self, source, target, clearance, tolerance, budget)
        if not self.snapshot_attached: value.result = self._session._clear_step()
        return value

    def close(self):
        self.broker.defer_close(self._session)

    def __getattr__(self, name):
        return getattr(self._session, name)


class V3NativeOperationExperiment:
    def __init__(self, collection_ms=0.25, retain_trace=False, force_broker=False):
        self.collection_ms = max(0.0, float(collection_ms)); self.waves = self.jobs = 0
        self.workers = self.measures = self.structurals = self.sweeps = 0
        self.retain_trace, self.force_broker = bool(retain_trace), bool(force_broker)
        self.operations, self._broker = [], None

    def run(self, sessions):
        rows, started = tuple(sessions), perf_counter()
        if len(rows) < 2 and not (self.retain_trace or self.force_broker): return self._run_single(rows, started)
        broker = _OperationBroker(len(rows), self.collection_ms, self.retain_trace or self.force_broker)
        self._broker = broker
        with ThreadPoolExecutor(max_workers=max(1, len(rows))) as pool:
            futures = tuple(pool.submit(_drive_session, row, broker) for row in rows)
            self._drain(broker); _raise_driver_errors(futures)
        if not self.retain_trace: self.release_trace()
        return self._report(1000.0 * (perf_counter() - started))

    def _run_single(self, sessions, started):
        for session in sessions:
            while not session.done: session.step()
        return self._report(1000.0 * (perf_counter() - started))

    def _drain(self, broker):
        while broker.active:
            calls = broker.take()
            if not calls: continue
            try: stats = execute_native_operations(tuple(row.operation for row in calls))
            except Exception as error: broker.fail(calls, error); broker.abort(error); raise
            self._record(stats, calls); broker.complete(calls)

    def _record(self, stats, calls):
        self.waves += 1; self.jobs += int(stats.submitted)
        self.workers = max(self.workers, int(stats.workers_used))
        self.measures += int(stats.measures); self.structurals += int(stats.structurals)
        self.sweeps += int(stats.sweeps)
        if self.retain_trace: self.operations.extend(row.operation for row in calls)

    def replay(self):
        before = tuple(_operation_fingerprint(row) for row in self.operations)
        sweep_before = tuple(_sweep_signature(row) for row in self.operations if row.kind == SWEEP)
        checks_before = _validate_coordinator_sweeps(self.operations)
        coordinator = execute_native_coordinator(tuple(self.operations))
        after = tuple(_operation_fingerprint(row) for row in self.operations)
        sweep_after = tuple(_sweep_signature(row) for row in self.operations if row.kind == SWEEP)
        checks = _validate_coordinator_sweeps(self.operations)
        return _replay_report(coordinator, self.operations, before, after, sweep_before, sweep_after,
                              checks_before, checks)

    def release_trace(self):
        if self._broker is not None: self._broker.close_sessions()
        self._broker = None

    def _report(self, elapsed):
        return V3OperationReport(elapsed, self.waves, self.jobs, self.workers,
                                 self.measures, self.structurals, self.sweeps)


class V3NativeCoordinatorLiveExperiment(V3NativeOperationExperiment):
    def __init__(self, collection_ms=0.25):
        super().__init__(collection_ms, False, True)

    def _drain(self, broker):
        while broker.active:
            calls = broker.take()
            if not calls: continue
            try: stats = execute_native_coordinator(tuple(row.operation for row in calls))
            except Exception as error: broker.fail(calls, error); broker.abort(error); raise
            self._record_live(stats, calls); broker.complete(calls)

    def _record_live(self, stats, calls):
        self.waves += 1; self.jobs += len(calls); self.workers = max(self.workers, stats.workers_used)
        self.measures += sum(row.operation.kind == MEASURE for row in calls)
        self.structurals += sum(row.operation.kind == STRUCTURAL for row in calls)
        self.sweeps += sum(row.operation.kind == SWEEP for row in calls)


def _measure_payload(low, values, rows, arrays, span, activation, threshold):
    return _MeasurePayload(low.handle, cn._double(values), float(span), float(activation), float(threshold),
        rows, len(rows), 0, cn._NativeWorldContacts(), cn._plain(arrays[0]), cn._plain(arrays[1]),
        cn._double(arrays[2]), cn._NativeWorldBatch())


def _structural_payload(low, bands, rhs, arrays, pins, targets, output, responses, count):
    return _StructuralPayload(low.handle, *(cn._double(row) for row in bands), cn._double(rhs),
        cn._integer(arrays[0]), cn._double(arrays[1]), cn._double(arrays[2]), len(arrays[0]),
        cn._integer(pins), cn._double(targets), len(pins), count, cn._double(output),
        cn._double(responses), cn._NativeBlockResult())


def _configure_operations(library):
    function = library.af_v3_execute_operations
    function.argtypes = [POINTER(_OperationDescriptor), c_int, POINTER(_OperationStats)]
    function.restype = c_int; return function


def execute_native_operations(operations):
    rows = tuple(operations); descriptors = tuple(row.descriptor(index) for index, row in enumerate(rows))
    values = (_OperationDescriptor * len(rows))(*descriptors); stats = _OperationStats()
    function = _configure_operations(rows[0].session.native.library)
    if function(values, len(values), byref(stats)): raise RuntimeError("native V3 operation wave failed")
    for operation, descriptor in zip(rows, values): operation.accept(descriptor)
    return stats


def execute_native_coordinator(operations):
    rows = tuple(operations); descriptors = tuple(row.descriptor(index) for index, row in enumerate(rows))
    values = (_OperationDescriptor * len(rows))(*descriptors); stats = _CoordinatorStats()
    function = _configure_coordinator(rows[0].session.native.library)
    if function(values, len(values), byref(stats)): raise RuntimeError("native V3 coordinator failed")
    for operation, descriptor in zip(rows, values): operation.accept(descriptor)
    return _coordinator_report(stats)


class V3PersistentNativeCoordinator:
    def __init__(self, operations):
        self.operations = tuple(operations)
        rows = tuple(row.descriptor(index) for index, row in enumerate(self.operations))
        self.values = (_OperationDescriptor * len(rows))(*rows)
        self.library = self.operations[0].session.native.library
        self.handle = None; self.create, self.advance, self.destroy = _configure_persistent(self.library)
        self.handle = self.create(self.values, len(self.values))
        if not self.handle: raise RuntimeError("native V3 coordinator creation failed")

    def step(self, budget_ms=12.0):
        stats, done = _CoordinatorStats(), c_int()
        if self.advance(self.handle, float(budget_ms), byref(stats), byref(done)):
            raise RuntimeError("native V3 coordinator step failed")
        self._accept_completed(); return _coordinator_report(stats), bool(done.value)

    def _accept_completed(self):
        for operation, descriptor in zip(self.operations, self.values):
            if descriptor.status != -1: operation.accept(descriptor)

    def close(self):
        if getattr(self, "handle", None): self.destroy(self.handle); self.handle = None

    def __del__(self):
        self.close()


def _configure_coordinator(library):
    function = library.af_v3_coordinator_execute
    function.argtypes = [POINTER(_OperationDescriptor), c_int, POINTER(_CoordinatorStats)]
    function.restype = c_int; return function


def _configure_persistent(library):
    create, advance, destroy = (library.af_v3_coordinator_create, library.af_v3_coordinator_step,
                                library.af_v3_coordinator_destroy)
    create.argtypes, create.restype = [POINTER(_OperationDescriptor), c_int], c_void_p
    advance.argtypes = [c_void_p, c_double, POINTER(_CoordinatorStats), POINTER(c_int)]
    advance.restype = c_int; destroy.argtypes = [c_void_p]; destroy.restype = None
    return create, advance, destroy


def _coordinator_report(stats):
    names = ("operations", "streams", "contact_jobs", "validation_jobs", "structural_jobs",
             "ccd_broad_jobs", "ccd_pair_jobs", "workers", "workers_used")
    values = [int(getattr(stats, name)) for name in names]
    return V3CoordinatorReport(*values, bool(stats.deterministic), float(stats.elapsed_ms))


class _OperationBroker:
    def __init__(self, active, collection_ms, force=False):
        self.active, self.collection = int(active), float(collection_ms) / 1000.0
        self.condition, self.queue, self.error = Condition(), [], None
        self.deferred_sessions, self.force = [], bool(force)

    def submit(self, operation):
        call = _PendingCall(operation)
        with self.condition:
            if self.error is not None: raise self.error
            self.queue.append(call); self.condition.notify_all()
        call.event.wait()
        if call.error is not None: raise call.error
        return operation.result()

    def shared(self):
        with self.condition: return (self.active > 1 or self.force) and self.error is None

    def take(self):
        with self.condition:
            while not self.queue and self.active and self.error is None: self.condition.wait()
            if self.queue and len(self.queue) < self.active: self.condition.wait(self.collection)
            rows, self.queue = tuple(self.queue), []
        return rows

    def complete(self, calls):
        for call in calls: call.event.set()

    def finish(self):
        with self.condition: self.active -= 1; self.condition.notify_all()

    def abort(self, error):
        with self.condition:
            self.error = error; rows, self.queue = tuple(self.queue), []
            self.condition.notify_all()
        for call in rows: call.error = error; call.event.set()

    def fail(self, calls, error):
        for call in calls: call.error = error; call.event.set()

    def defer_close(self, session):
        if all(row is not session for row in self.deferred_sessions): self.deferred_sessions.append(session)

    def close_sessions(self):
        rows, self.deferred_sessions = tuple(self.deferred_sessions), []
        for session in rows: session.close()


def _drive_session(session, broker):
    try:
        while not session.done:
            _wrap_session_natives(session, broker); session.step()
        return session.package
    except Exception as error:
        broker.abort(error); session.cancel(); raise
    finally: broker.finish()


def _wrap_session_natives(session, broker):
    for span in session.spans:
        state = span.state
        if state is None or state.native_session is None: continue
        if not isinstance(state.native_session, V3OperationSessionProxy):
            state.native_session = V3OperationSessionProxy(state.native_session, broker)


def _raise_driver_errors(futures):
    for future in futures: future.result()


def _operation_fingerprint(operation):
    digest = hashlib.sha256(); digest.update(int(operation.kind).to_bytes(2, "little"))
    for value in _operation_outputs(operation): digest.update(value)
    return digest.digest()


def _operation_outputs(operation):
    if operation.kind == MEASURE: return _measure_outputs(operation)
    if operation.kind == STRUCTURAL: return _structural_outputs(operation)
    return _sweep_outputs(operation)


def _measure_outputs(operation):
    arrays = operation.references[2]; rows = operation.references[1]
    values = [bytes(rows), bytes(operation.payload.contacts), bytes(operation.payload.validation)]
    values.extend(np.asarray(row).tobytes() for row in arrays); return tuple(values)


def _structural_outputs(operation):
    result = operation.payload.result
    metadata = np.asarray((result.condition, result.count, result.valid), dtype=np.float64).tobytes()
    return (operation.references[-2].tobytes(), operation.references[-1].tobytes(),
            metadata)


def _sweep_outputs(operation):
    payload = operation.payload
    values = (bytes(payload.result), int(payload.candidates), int(payload.pairs),
              int(payload.edge), int(payload.face), int(payload.status))
    return tuple(value if isinstance(value, bytes) else int(value).to_bytes(8, "little", signed=True)
                 for value in values)


def _replay_report(coordinator, operations, before, after, sweep_before, sweep_after, before_checks, checks):
    mismatches = {MEASURE: 0, STRUCTURAL: 0, SWEEP: 0}
    for operation, first, second in zip(operations, before, after):
        mismatches[operation.kind] += int(first != second)
    exact = len(operations) - sum(mismatches.values())
    delta = max((abs(a[0] - b[0]) for a, b in zip(sweep_before, sweep_after)), default=0.0)
    permissive = sum(b[0] > a[0] + 1.0e-12 for a, b in zip(sweep_before, sweep_after))
    valid = sum(a[1] != b[1] for a, b in zip(sweep_before, sweep_after))
    return V3CoordinatorReplayReport(coordinator, len(operations), exact,
        mismatches[MEASURE], mismatches[STRUCTURAL], mismatches[SWEEP], delta, permissive, valid,
        before_checks, checks)


def _sweep_signature(operation):
    result = operation.payload.result
    return float(result.safe), int(result.valid), int(result.reason), int(operation.payload.edge), int(operation.payload.face)


def _validate_coordinator_sweeps(operations):
    spans, failures = {}, 0
    for operation in operations:
        key = id(operation.session)
        if operation.kind == MEASURE: spans[key] = operation.payload.span
        elif operation.kind == SWEEP: failures += int(not _coordinator_sweep_clear(operation, spans.get(key, 0.0)))
    return failures


def _coordinator_sweep_clear(operation, span):
    payload = operation.payload; result = payload.result
    if not result.valid or result.safe <= 0.0: return True
    source, target = (np.asarray(row) for row in payload._arrays[:2])
    points = source + min(1.0, .999 * result.safe) * (target - source)
    validation = operation.session.validate(points, span, payload.clearance)
    return bool(all(validation.clear))


@contextmanager
def experimental_backend():
    previous = cn._DEFAULT_NATIVE_PATH
    _set_backend(EXPERIMENT_DLL)
    try: yield EXPERIMENT_DLL
    finally: _set_backend(previous)


def _set_backend(path):
    clear_native_collision_world_cache(); clear_triangle_snapshot_cache(); cn.clear_native_libraries()
    cn._DEFAULT_NATIVE_PATH = Path(path)
