"""Package 7.1 fixed-reference Fiber V2 experiment."""

from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter

import numpy as np

from .contracts import V2Diagnostics, V2Termination
from .structural import solve_structural, structural_energy, structural_gradient
from . import solver as p5
from . import solver_p6 as p6
from . import solver_p61 as p61


V2_SOLVER_P71_VERSION = "fiber-v2-solver-package7.1-1"


@dataclass(frozen=True)
class V2Package71Trace(p61.V2Package61Trace):
    fixed_reference: bool = True
    reference_signature: str = ""
    stationarity_history: tuple = ()
    model_ms: float = 0.0


def solve_package71(request, snapshot=None, contact_weight=p5.DEFAULT_CONTACT_WEIGHT):
    started = perf_counter(); triangle = snapshot or p5.build_triangle_snapshot(request.colliders)
    planner = p5._package5_planner(request, triangle)
    if not planner.succeeded:
        return _failed(request, planner, started, contact_weight)
    state = p6._state(request, p5._solver_planner(request, planner), triangle, contact_weight)
    _initialize(state); first = _candidate(state); state.workload = p61._dispatch_probe(state, first)
    termination, message = _iterate(state, first); return _finish(state, termination, message, started)


def _initialize(state):
    p5._prepare_contacts(state); p61._initialize_dispatch(state)
    state.stationarity_history = []; state.model_ms = 0.0


def _candidate(state):
    started = perf_counter(); state.contact_changed = p5._refresh_native_contacts(state)
    state.structural = _structural_candidate(state)
    candidate = _surface_or_contact_candidate(state)
    state.model_ms += p5._elapsed(started); return p5._record_candidate(state, candidate)


def _structural_candidate(state):
    started = perf_counter(); solved = solve_structural(state.reference, state.pins, state.request.settings)
    state.solve_ms += p5._elapsed(started); return solved.points.copy()


def _surface_or_contact_candidate(state):
    if state.planner.mode.value == "SURFACE":
        p5._clear_native_contacts(state); return p5._surface_candidate(state)
    return p5._metric_project(state, state.structural) if state.active else state.structural


def _iterate(state, first):
    if state.certificates_enabled:
        return _iterate_trust(state, state.dispatch_candidate)
    return _iterate_fast(state, first)


def _iterate_fast(state, first):
    for trial in range(state.request.settings.max_accepted_steps):
        state.trials += 1; candidate = first if trial == 0 else _candidate(state)
        changed = state.contact_changed; accepted, full = _accept_curved(state, candidate)
        if accepted and _converged(state, full, changed, 0):
            return V2Termination.CONVERGED, "fixed-reference local/global fixed point"
        if not accepted and not changed:
            return V2Termination.BLOCKED, "fixed-reference P5.1 step is blocked"
    return V2Termination.BUDGET_EXHAUSTED, "accepted-step cap exhausted"


def _iterate_trust(state, first):
    for trial in range(state.request.settings.max_accepted_steps):
        state.trials += 1; candidate, clipped = ((first, state.dispatch_clipped) if trial == 0 else _bounded(state))
        changed = state.contact_changed; accepted, full, step = _accept_trust(state, candidate)
        p6._update_trust(state, accepted, full, step); state.clipped_nodes.append(clipped)
        terminal = _trust_terminal(state, accepted, full, clipped, changed, step)
        if terminal is not None:
            return terminal
    return V2Termination.BUDGET_EXHAUSTED, "accepted-step cap exhausted"


def _bounded(state):
    return p6._bounded_candidate(state, _candidate(state))


def _accept_curved(state, candidate):
    waypoints = p5._curved_waypoints(state, candidate)
    envelope = p5._waypoint_envelope(state.points, waypoints)
    return _accept_waypoints(state, waypoints, envelope)


def _accept_waypoints(state, waypoints, envelope):
    source = state.points
    for target in waypoints:
        step = _timed_safe_step(state, source, target, envelope)
        proposed, full = p5._ccd_proposal(source, target, step)
        if proposed is None:
            return _reject(state)
        if not full:
            return _accept_model(state, proposed, False)
        source = target
    return _accept_model(state, source, True)


def _timed_safe_step(state, source, target, envelope):
    started = perf_counter(); step = p5._safe_step_p51(state, source, target, envelope)
    state.ccd_ms += p5._elapsed(started); p5._absorb_ccd(state, step); return step


def _accept_trust(state, candidate):
    started = perf_counter(); step = p6._safe_step(state, candidate)
    state.ccd_ms += p5._elapsed(started); p5._absorb_ccd(state, step); state.ccd_intervals += step.intervals
    proposed, full = p5._ccd_proposal(state.points, candidate, step)
    if proposed is None:
        state.rejected += 1; return False, False, step
    prior = state.points.copy(); accepted, full = _accept_model(state, proposed, full)
    if accepted:
        state.distance_cache.advance(p6._edges(state), prior, state.points)
    return accepted, full, step


def _accept_model(state, proposed, full):
    current, merit = _merit(state, state.points), _merit(state, proposed)
    if merit > current + 1.0e-12 * max(1.0, current):
        return _reject(state)
    state.last_step = p5._normalized_step(state, proposed); state.points = np.asarray(proposed)
    state.accepted.append(float(merit)); state.stationarity_history.append(_stationarity(state))
    return True, bool(full)


def _reject(state):
    state.rejected += 1; return False, False


def _merit(state, points):
    return float(structural_energy(points, state.reference, state.request.settings).total)


def _stationarity(state):
    gradient = structural_gradient(state.points, state.reference, state.pins, state.request.settings)
    residual = _projected_gradient(state, gradient)
    scale = max(state.request.tolerances.length_scale, 1.0e-12)
    return float(np.max(np.linalg.norm(residual, axis=1)) / scale) if len(residual) else 0.0


def _projected_gradient(state, gradient):
    matrix = _constraint_matrix(state)
    if not len(matrix):
        return np.asarray(gradient)
    values = np.asarray(gradient).reshape(-1); weights = np.linalg.lstsq(matrix.T, values, rcond=1.0e-10)[0]
    return (values - matrix.T @ weights).reshape((-1, 3))


def _constraint_matrix(state):
    free = [index for index in range(len(state.points)) if index not in state.pins]
    lookup = {index: row for row, index in enumerate(free)}; rows = []
    for indices, weights, normal in state.contact_rows:
        row = np.zeros((len(free), 3), dtype=np.float64)
        for index, weight in zip(indices, weights):
            if index in lookup:
                row[lookup[index]] += float(weight) * normal
        rows.append(row.reshape(-1))
    return np.asarray(rows, dtype=np.float64).reshape((-1, 3 * len(free)))


def _converged(state, full, changed, clipped):
    tolerance = state.request.tolerances
    return bool(full and not changed and not clipped and state.fixed_residual <= tolerance.fixed_point_tolerance
                and _stationarity(state) <= tolerance.stationarity_tolerance)


def _trust_terminal(state, accepted, full, clipped, changed, step):
    if not step.valid and step.reason.value == "BACKEND_UNAVAILABLE":
        return V2Termination.BACKEND_UNAVAILABLE, "native collision backend unavailable"
    if accepted and _converged(state, full, changed, clipped):
        return V2Termination.CONVERGED, "fixed-reference trust fixed point"
    state.zero_steps = state.zero_steps + 1 if step.safe_step <= 1.0e-12 and not changed else 0
    if state.zero_steps >= 2 and state.trust_radius <= state.min_trust * (1.0 + 1.0e-12):
        return V2Termination.BLOCKED, "fixed-reference minimum trust is CCD-blocked"
    return None


def _finish(state, termination, message, started):
    checked = p5._timed_validation(state, state.points); diagnostics = _diagnostics(state, checked)
    validated = bool(checked.valid and np.isfinite(state.points).all())
    if not validated:
        termination, message = V2Termination.UNSAFE_OUTPUT, "final independent validation failed"
    result = p5._result(state.request, state.planner, state.points, diagnostics,
                        termination, validated, message, V2_SOLVER_P71_VERSION)
    return p5.V2Package5Result(result, state.planner, _trace(state, started))


def _diagnostics(state, checked):
    energy = structural_energy(state.points, state.reference, state.request.settings)
    contact = p5._contact_energy(state, checked)
    return V2Diagnostics(energy.fidelity, energy.length, energy.curvature, contact,
                         state.fixed_residual, _stationarity(state), checked.node_residual,
                         checked.edge_residual, state.fractions[-1] if state.fractions else 1.0,
                         state.ccd_pairs, state.ccd_tested, len(state.accepted), state.rejected, 0)


def _trace(state, started):
    base = p61._trace(state, started)
    return V2Package71Trace(**vars(base), fixed_reference=True,
                            reference_signature=_reference_signature(state.reference),
                            stationarity_history=tuple(state.stationarity_history),
                            model_ms=float(state.model_ms))


def _reference_signature(reference):
    return sha256(np.asarray(reference, dtype=np.float64).tobytes()).hexdigest()


def _failed(request, planner, started, contact_weight):
    result = p5._result(request, planner, (), V2Diagnostics(), planner.termination, False,
                        planner.message, V2_SOLVER_P71_VERSION)
    trace = V2Package71Trace(total_ms=p5._elapsed(started), contact_weight=float(contact_weight))
    return p5.V2Package5Result(result, planner, trace)
