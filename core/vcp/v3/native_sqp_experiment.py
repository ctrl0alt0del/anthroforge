"""Isolated whole-controller native SQP experiment; production V3 never imports this module."""

from ctypes import POINTER, Structure, byref, c_double, c_int, c_int64, c_void_p
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import numpy as np

from ..v2 import collision_native as cn
from ..v2.contact_core import _owner_span, _true_length_epsilon
from .native_operation_experiment import _set_backend
from .production import begin_v3
from .solver import _validate_live
from .spans import synchronize_owner_spans


EXPERIMENT_DLL = Path(__file__).resolve().parents[3] / "native/fiber_ccd/af_fiber_ccd_v3_sqp_experiment.dll"
LEGACY_CCD, INDEXED_CCD = 0, 1
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
    maximum_violation: float; trajectory: tuple


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

    def points(self):
        rows = []
        for reference in self.refs:
            values = reference[4]; rows.extend(values if not rows else values[1:])
        return np.ascontiguousarray(rows, dtype=np.float64)


def solve_native_sqp(request, ccd_mode=INDEXED_CCD, use_planner=True):
    previous = cn._DEFAULT_NATIVE_PATH; _set_backend(EXPERIMENT_DLL)
    session = begin_v3(request, preview=False, use_planner=use_planner, native_controller=False)
    try: return _solve_session(session, ccd_mode)
    finally: session.cancel(); _set_backend(previous)


def _solve_session(session, ccd_mode):
    _prime(session); invocation = _Invocation(session, ccd_mode); elapsed = invocation.run()
    points = invocation.points(); valid = bool(len(points) and _validate_live(session, points))
    spans = tuple(_span_report(row.result, reference[5:])
                  for row, reference in zip(invocation.jobs, invocation.refs))
    mode = "INDEXED" if ccd_mode == INDEXED_CCD else "LEGACY"
    return NativeSqpReport(points, spans, elapsed, valid, mode)


def _prime(session):
    while not session.done and session.phase != "SOLVE": session.step()
    if session.done or not session.spans: raise RuntimeError("V3 session did not produce spans")
    for span in session.spans:
        while not span.done and span.phase != "SOLVE": span.step()
        if span.done: raise RuntimeError("V3 span failed during initialization")
    synchronize_owner_spans(session.spans, session.request, session.pins)


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


def _span_report(row, traces):
    integers = (row.accepted, row.rejected, row.trials, row.contacts, row.ccd_pairs, row.ccd_tests)
    values = (row.energy, row.fixed_residual, row.stationarity, row.regularization,
              row.trust_radius, row.maximum_violation)
    return NativeSqpSpanReport(_TERMINATIONS.get(row.termination, "UNKNOWN"), *integers,
        bool(row.spacing_enabled), bool(row.validated), *values, _trajectory(row.trace_count, traces))


def _trajectory(count, traces):
    safe, ratio, violation, decisions, edges, faces = traces; output = []
    for index in range(int(count)):
        output.append((index + 1, _DECISIONS.get(int(decisions[index]), "UNKNOWN"),
            float(safe[index]), float(ratio[index]), float(violation[index]),
            int(edges[index]), int(faces[index])))
    return tuple(output)
