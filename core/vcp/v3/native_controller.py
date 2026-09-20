"""Production bridge for persistent synchronous and asynchronous native V3 controllers."""

import atexit
from ctypes import POINTER, Structure, byref, c_double, c_int, c_int64, c_uint64, c_void_p
from dataclasses import dataclass
from time import perf_counter

import numpy as np

from ..v2 import collision_native as cn
from ..v2.contact_core import (_finish_contact_session, _owner_span,
                               _refresh_state, _true_length_epsilon)
from ..v2.contracts import V2Termination
from .solver import _synchronize_spans, _validate_live


LEGACY_CCD, INDEXED_CCD = 0, 1
_ASYNC_COORDINATORS = {}
_TERMINATIONS = {1: "CONVERGED", 2: "STALLED", 3: "BUDGET_EXHAUSTED", 4: "UNSAFE_OUTPUT"}
_DECISIONS = {0: "NONE", 1: "ACCEPT", 2: "REJECT", 3: "INJECT", 4: "CCD_REJECT", 5: "SOLVE_FAIL"}


class _SqpConfig(Structure):
    _fields_ = [(name, c_double) for name in ("length_weight", "fidelity_weight", "epsilon",
        "radius", "slack", "owner_span", "numeric_floor", "length_scale", "fixed_tolerance",
        "stationarity_tolerance", "relative_energy_tolerance", "trust_radius", "min_trust",
        "max_trust", "regularization", "regularization_scale", "penalty")]
    _fields_ += [(name, c_int) for name in ("accepted_cap", "trial_cap", "ccd_mode", "ccd_budget")]


class _SqpResult(Structure):
    _fields_ = [(name, c_int) for name in ("termination", "accepted", "rejected", "trials",
        "contacts", "ccd_pairs", "ccd_tests", "spacing_enabled", "validated", "trace_count")]
    _fields_ += [(name, c_int) for name in ("feasibility_iterations", "multiplier_updates",
        "regularization_increases", "regularization_decreases", "injected_contacts",
        "limiting_contacts", "contact_groups")]
    _fields_ += [(name, c_double) for name in ("energy", "fixed_residual", "stationarity",
        "regularization", "trust_radius", "maximum_violation", "elapsed_ms")]


class _SqpBatchStats(Structure):
    _fields_ = [(name, c_int) for name in
                ("sessions", "active", "stepped", "completed", "workers", "trials")]
    _fields_ += [("elapsed_ms", c_double)]


class _SqpAsyncStatus(Structure):
    _fields_ = [("revision", c_uint64)]
    _fields_ += [(name, c_int) for name in
                 ("state", "code", "done", "accepted", "infeasible", "workers", "trials")]
    _fields_ += [("elapsed_ms", c_double)]


class _SqpJob(Structure):
    _fields_ = [("session", c_void_p), ("points", POINTER(c_double)),
                ("reference", POINTER(c_double)), ("count", c_int)]
    _fields_ += [("pins", POINTER(c_int64)), ("targets", POINTER(c_double)),
                 ("pin_count", c_int), ("config", _SqpConfig)]
    _fields_ += [(name, POINTER(c_double)) for name in
                 ("output", "safe_history", "ratio_history", "violation_history")]
    _fields_ += [(name, POINTER(c_int)) for name in
                 ("decision_history", "limiting_edges", "limiting_faces")]
    _fields_ += [("result", _SqpResult)]


@dataclass(frozen=True)
class NativeSqpSpanReport:
    termination: str; accepted: int; rejected: int; trials: int; contacts: int
    ccd_pairs: int; ccd_tests: int; spacing: bool; validated: bool
    energy: float; fixed: float; stationarity: float; regularization: float; trust_radius: float
    maximum_violation: float; trajectory: tuple; points: np.ndarray
    feasibility_iterations: int = 0; multiplier_updates: int = 0
    regularization_increases: int = 0; regularization_decreases: int = 0
    injected_contacts: int = 0; limiting_contacts: int = 0; contact_groups: int = 0


@dataclass(frozen=True)
class NativeSqpReport:
    points: np.ndarray; spans: tuple; elapsed_ms: float; validated: bool; ccd_mode: str


class _Invocation:
    def __init__(self, session, mode):
        self.session, self.mode, self.refs = session, int(mode), []
        self.jobs = (_SqpJob * len(session.spans))()
        for index, span in enumerate(session.spans): self.jobs[index] = self._job(span)

    def _job(self, span):
        state = span.state; arrays = _arrays(state); output = np.empty_like(arrays[0])
        config = _config(state, self.mode); trace = _trace_arrays(config.trial_cap)
        self.refs.append((*arrays, output, *trace))
        return _SqpJob(state.native_session.native.handle, cn._double(arrays[0]),
            cn._double(arrays[1]), len(arrays[0]), cn._integer(arrays[2]), cn._double(arrays[3]),
            len(arrays[2]), config, cn._double(output), *(cn._double(row) for row in trace[:3]),
            *(cn._plain(row) for row in trace[3:]), _SqpResult())

    def run(self):
        cap = self.session.request.settings.max_accepted_steps; trials = max(32, 8 * cap)
        function = _configure(self.session.spans[0].state.native_session.native.library)
        started = perf_counter(); code = function(self.jobs, len(self.jobs), cap, trials)
        if code: raise RuntimeError(f"native V3 SQP controller failed: {code}")
        return 1000.0 * (perf_counter() - started)

    def begin(self):
        library = self.session.spans[0].state.native_session.native.library
        _configure_resumable(library); cap = self.session.request.settings.max_accepted_steps
        handle = library.af_v3_native_sqp_begin(self.jobs, len(self.jobs), cap, max(32, 8 * cap))
        if not handle: raise RuntimeError("native V3 SQP coordinator creation failed")
        return handle

    def points(self):
        rows = []
        for reference in self.refs:
            values = reference[4]; rows.extend(values if not rows else values[1:])
        return np.ascontiguousarray(rows, dtype=np.float64)


class NativeControllerRun:
    def __init__(self, session, ccd_mode=INDEXED_CCD):
        self.session, self.mode = session, int(ccd_mode); self.invocation = _Invocation(session, ccd_mode)
        self.library = session.spans[0].state.native_session.native.library
        self.handle = self.invocation.begin(); self.done = False; self.accepted = 0; self.infeasible = True
        self.externally_advanced = False; self.async_owner = None; self.async_task = 0
        self.async_trials = 0; self.async_elapsed = 0.0

    def step(self, trials=1):
        if self.async_owner is not None:
            self.async_owner.poll((self,)); return self.done
        done, accepted, infeasible = c_int(), c_int(), c_int()
        code = self.library.af_v3_native_sqp_step(
            self.handle, max(1, int(trials)), byref(done), byref(accepted), byref(infeasible))
        if code: raise RuntimeError(f"native V3 SQP coordinator step failed: {code}")
        self.done, self.accepted, self.infeasible = bool(done.value), accepted.value, bool(infeasible.value)
        _publish_working(self.session, self.invocation); return self.done

    def finish(self):
        if self.async_owner is not None: self.async_owner.detach(self, cancel=False)
        if not self.done and self.library.af_v3_native_sqp_finish(self.handle):
            raise RuntimeError("native V3 SQP coordinator finish failed")
        report = _invocation_report(self.invocation, self.mode); self.close(); return report

    def cancel(self):
        if self.async_owner is not None: self.async_owner.detach(self, cancel=True)
        if self.handle: self.library.af_v3_native_sqp_cancel(self.handle)
        self.close()

    def close(self):
        if self.async_owner is not None: self.async_owner.detach(self, cancel=not self.done)
        if self.handle: self.library.af_v3_native_sqp_destroy(self.handle); self.handle = None

    def __del__(self):
        try: self.close()
        except Exception: pass


class NativeAsyncCoordinator:
    def __init__(self, library, trials=4):
        self.library = library; _configure_async(library)
        self.handle = library.af_v3_async_sqp_create(max(1, int(trials)))
        if not self.handle: raise RuntimeError("native asynchronous V3 coordinator creation failed")
        self.runs = {}

    def submit(self, run):
        if run.async_task: return
        task = c_uint64(); code = self.library.af_v3_async_sqp_submit(self.handle, run.handle, byref(task))
        if code: raise RuntimeError(f"native asynchronous V3 submission failed: {code}")
        run.async_task, run.async_owner = int(task.value), self; self.runs[run.async_task] = run

    def poll(self, runs):
        active = tuple(run for run in runs if run.handle and not run.done)
        for run in active: self.submit(run)
        if not active: return _empty_batch_report()
        return self._poll_rows(active)

    def _poll_rows(self, runs):
        ids = (c_uint64 * len(runs))(*(run.async_task for run in runs)); rows = (_SqpAsyncStatus * len(runs))()
        started = perf_counter(); code = self.library.af_v3_async_sqp_poll_many(self.handle, ids, len(runs), rows)
        if code: raise RuntimeError(f"native asynchronous V3 poll failed: {code}")
        elapsed = 1000.0 * (perf_counter() - started); return _install_async_rows(runs, rows, elapsed)

    def detach(self, run, cancel):
        task = int(run.async_task or 0)
        if not task: return
        if cancel and self.library.af_v3_async_sqp_cancel(self.handle, task):
            raise RuntimeError("native asynchronous V3 cancellation failed")
        code = self.library.af_v3_async_sqp_remove(self.handle, task)
        if code: raise RuntimeError(f"native asynchronous V3 removal failed: {code}")
        self.runs.pop(task, None); run.async_task, run.async_owner = 0, None

    def close(self):
        if not self.handle: return
        for run in tuple(self.runs.values()): self.detach(run, cancel=not run.done)
        self.library.af_v3_async_sqp_destroy(self.handle); self.handle = None

    @property
    def active(self):
        return bool(self.runs)


def solve_native_controller(session, ccd_mode=INDEXED_CCD):
    if not cn.native_controller_status(): raise RuntimeError("native V3 controller is unavailable")
    report = _solve_session(session, ccd_mode); _install_report(session, report)
    from .solver import _finalize
    _finalize(session); return session.package, report


def _solve_session(session, ccd_mode):
    _prime(session); run = NativeControllerRun(session, ccd_mode)
    while not run.done: run.step(64)
    return run.finish()


def begin_native_controller(session, ccd_mode=INDEXED_CCD):
    if not cn.native_controller_status(): raise RuntimeError("native V3 controller is unavailable")
    return NativeControllerRun(session, ccd_mode)


def step_native_controllers(runs, trials=1):
    active = tuple(run for run in runs if run.handle and not run.done)
    if not active: return _empty_batch_report()
    library = active[0].library; _configure_many(library)
    handles = (c_void_p * len(active))(*(run.handle for run in active))
    results = np.empty(3 * len(active), dtype=np.int32); stats = _SqpBatchStats()
    code = library.af_v3_native_sqp_step_many(handles, len(active), max(1, int(trials)), cn._plain(results), byref(stats))
    if code: raise RuntimeError(f"native V3 multi-session step failed: {code}")
    _install_batch_rows(active, results); return _batch_report(stats)


def poll_native_controllers(runs):
    active = tuple(run for run in runs if run.handle and not run.done)
    if not active: return _empty_batch_report()
    if not cn.native_async_controller_status(): raise RuntimeError("native asynchronous V3 coordinator is unavailable")
    return _async_coordinator(active[0].library).poll(active)


def native_async_controllers_active():
    return any(row.active for row in _ASYNC_COORDINATORS.values())


def shutdown_native_async_controllers():
    for value in tuple(_ASYNC_COORDINATORS.values()): value.close()
    _ASYNC_COORDINATORS.clear()


def _async_coordinator(library):
    key = id(library)
    if key not in _ASYNC_COORDINATORS: _ASYNC_COORDINATORS[key] = NativeAsyncCoordinator(library)
    return _ASYNC_COORDINATORS[key]


def finish_native_controller(session, run):
    report = run.finish(); _install_report(session, report); return report


def _prime(session):
    while not session.done and session.phase not in {"SOLVE", "NATIVE_INIT"}: session.step()
    if session.done or not session.spans: raise RuntimeError("V3 session did not produce spans")
    for span in session.spans:
        while not span.done and span.phase != "SOLVE": span.step()
        if span.done: raise RuntimeError("V3 span failed during initialization")
    _synchronize_spans(session)


def _arrays(state):
    points = np.ascontiguousarray(state.points, dtype=np.float64)
    reference = np.ascontiguousarray(state.q, dtype=np.float64)
    pins = np.ascontiguousarray(tuple(state.pins), dtype=np.int64)
    targets = np.ascontiguousarray(tuple(state.pins[index] for index in pins), dtype=np.float64)
    return points, reference, pins, targets


def _trace_arrays(count):
    doubles = tuple(np.full(count, np.nan, dtype=np.float64) for _index in range(3))
    integers = tuple(np.full(count, -1, dtype=np.int32) for _index in range(3))
    return doubles + integers


def _config(state, mode):
    request, tolerance = state.request, state.request.tolerances
    settings, collision = request.settings, request.collision_policy
    doubles = (settings.length_weight, settings.fidelity_weight, _true_length_epsilon(state),
        collision.collision_radius, tolerance.clearance_slack, _owner_span(state),
        tolerance.numeric_floor, tolerance.length_scale, tolerance.fixed_point_tolerance,
        tolerance.stationarity_tolerance, tolerance.relative_energy_tolerance, state.trust_radius,
        state.min_trust, state.max_trust, state.sqp_regularization, state.regularization_scale, state.mu)
    cap = settings.max_accepted_steps; return _SqpConfig(*doubles, cap, max(32, 8 * cap), mode, 262143)


def _configure(library):
    function = library.af_v3_native_sqp_solve
    function.argtypes = [POINTER(_SqpJob), c_int, c_int, c_int]
    function.restype = c_int; return function


def _configure_resumable(library):
    library.af_v3_native_sqp_begin.argtypes = [POINTER(_SqpJob), c_int, c_int, c_int]
    library.af_v3_native_sqp_begin.restype = c_void_p
    library.af_v3_native_sqp_step.argtypes = [c_void_p, c_int, POINTER(c_int), POINTER(c_int), POINTER(c_int)]
    library.af_v3_native_sqp_step.restype = c_int
    library.af_v3_native_sqp_cancel.argtypes = [c_void_p]; library.af_v3_native_sqp_cancel.restype = c_int
    library.af_v3_native_sqp_finish.argtypes = [c_void_p]; library.af_v3_native_sqp_finish.restype = c_int
    library.af_v3_native_sqp_destroy.argtypes = [c_void_p]


def _configure_many(library):
    function = library.af_v3_native_sqp_step_many
    function.argtypes = [POINTER(c_void_p), c_int, c_int, POINTER(c_int), POINTER(_SqpBatchStats)]
    function.restype = c_int


def _configure_async(library):
    library.af_v3_async_sqp_create.argtypes = [c_int]; library.af_v3_async_sqp_create.restype = c_void_p
    library.af_v3_async_sqp_submit.argtypes = [c_void_p, c_void_p, POINTER(c_uint64)]
    library.af_v3_async_sqp_poll_many.argtypes = [c_void_p, POINTER(c_uint64), c_int, POINTER(_SqpAsyncStatus)]
    library.af_v3_async_sqp_cancel.argtypes = [c_void_p, c_uint64]
    library.af_v3_async_sqp_remove.argtypes = [c_void_p, c_uint64]
    library.af_v3_async_sqp_destroy.argtypes = [c_void_p]
    for name in ("submit", "poll_many", "cancel", "remove"): getattr(library, f"af_v3_async_sqp_{name}").restype = c_int


def _install_batch_rows(runs, values):
    for index, run in enumerate(runs):
        row = values[3 * index:3 * index + 3]
        run.done, run.accepted, run.infeasible = bool(row[0]), int(row[1]), bool(row[2])
        run.externally_advanced = True; _publish_working(run.session, run.invocation)


def _install_async_rows(runs, rows, poll_ms):
    trials = 0; elapsed = 0.0
    for run, row in zip(runs, rows):
        if row.code or row.state == 4: raise RuntimeError(f"native asynchronous V3 task failed: {row.code}")
        trials += max(0, int(row.trials) - run.async_trials)
        elapsed = max(elapsed, max(0.0, float(row.elapsed_ms) - run.async_elapsed))
        run.async_trials, run.async_elapsed = int(row.trials), float(row.elapsed_ms)
        run.done, run.accepted, run.infeasible = bool(row.done), int(row.accepted), bool(row.infeasible)
        run.externally_advanced = True
    workers = max((int(row.workers) for row in rows), default=0)
    return {"sessions": len(rows), "active": sum(not run.done for run in runs),
            "stepped": len(rows), "completed": sum(run.done for run in runs),
            "workers": workers, "trials": trials, "elapsed_ms": max(elapsed, poll_ms)}


def _batch_report(stats):
    return {name: getattr(stats, name) for name, _kind in stats._fields_}


def _empty_batch_report():
    return {"sessions": 0, "active": 0, "stepped": 0, "completed": 0,
            "workers": 0, "trials": 0, "elapsed_ms": 0.0}


def _publish_working(session, invocation):
    for span, reference in zip(session.spans, invocation.refs): span.state.points = reference[4].copy()


def _invocation_report(invocation, mode):
    values = invocation.points(); session = invocation.session
    points = values[:-1] if session.cyclic else values
    valid = bool(len(points) and _validate_live(session, points))
    spans = tuple(_span_report(row.result, reference[5:], reference[4])
                  for row, reference in zip(invocation.jobs, invocation.refs))
    elapsed = max((row.result.elapsed_ms for row in invocation.jobs), default=0.0)
    name = "INDEXED" if mode == INDEXED_CCD else "LEGACY"
    return NativeSqpReport(points, spans, elapsed, valid, name)


def _span_report(row, traces, points):
    integers = (row.accepted, row.rejected, row.trials, row.contacts, row.ccd_pairs, row.ccd_tests)
    values = (row.energy, row.fixed_residual, row.stationarity, row.regularization,
              row.trust_radius, row.maximum_violation)
    counters = (row.feasibility_iterations, row.multiplier_updates, row.regularization_increases,
        row.regularization_decreases, row.injected_contacts, row.limiting_contacts, row.contact_groups)
    return NativeSqpSpanReport(_TERMINATIONS.get(row.termination, "UNKNOWN"), *integers,
        bool(row.spacing_enabled), bool(row.validated), *values,
        _trajectory(row.trace_count, traces), np.ascontiguousarray(points.copy()), *counters)


def _trajectory(count, traces):
    safe, ratio, violation, decisions, edges, faces = traces; output = []
    for index in range(int(count)):
        output.append((index + 1, _DECISIONS.get(int(decisions[index]), "UNKNOWN"),
            float(safe[index]), float(ratio[index]), float(violation[index]),
            int(edges[index]), int(faces[index])))
    return tuple(output)


def _install_report(session, report):
    session.rounds = max((row.trials for row in report.spans), default=0)
    _prepare_report_install(session, report)
    for index, (span, row) in enumerate(zip(session.spans, report.spans)):
        _install_span(span, row); session.completed[index] = session.rounds


def _prepare_report_install(session, report):
    for span, row in zip(session.spans, report.spans): span.state.points = row.points.copy()
    _synchronize_spans(session)


def _install_span(session, report):
    state = session.state; state.points = report.points.copy()
    state.accepted, state.rejected = report.accepted, report.rejected
    state.fixed_residual, state.stationarity = report.fixed, report.stationarity
    state.sqp_regularization, state.trust_radius = report.regularization, report.trust_radius
    state.ccd_candidates, state.ccd_tested = report.ccd_pairs, report.ccd_tests
    state.quality_adapted = state.quality_spacing = report.spacing
    state.feasibility_iterations, state.multiplier_updates = report.feasibility_iterations, report.multiplier_updates
    state.regularization_increases = report.regularization_increases
    state.regularization_decreases = report.regularization_decreases
    state.injected, state.limiting = report.injected_contacts, report.limiting_contacts
    _install_histories(state, report); _refresh_state(state)
    _finish_contact_session(session, _termination(report, state), "persistent native V3 controller")


def _install_histories(state, report):
    state.fixed_history.append(report.fixed); state.stationarity_history.append(report.stationarity)
    state.regularization_history.append(report.regularization); state.trust_history.append(report.trust_radius)
    state.model_ratio_history.extend(row[3] for row in report.trajectory)
    state.ccd_step_history.extend(row[2] for row in report.trajectory)


def _termination(report, state):
    value = V2Termination(report.termination)
    return value if state.metrics.feasible else V2Termination.UNSAFE_OUTPUT


atexit.register(shutdown_native_async_controllers)
