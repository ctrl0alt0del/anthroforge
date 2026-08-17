"""Package 8 fixed contact-slot local/global Fiber V2 experiment."""

from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter

import numpy as np

from .contact_structural import contact_slot_energy, contact_stationarity, solve_contact_structural
from .contracts import V2Diagnostics, V2Termination
from .structural import solve_structural, structural_energy, structural_gradient
from . import solver as p5
from . import solver_p6 as p6


V2_SOLVER_P8_VERSION = "fiber-v2-solver-package8-1"
DEFAULT_SLOT_WEIGHT = 10.0


@dataclass(frozen=True)
class V2Package8Trace(p5.V2Package5Trace):
    acquisition_ms: float = 0.0
    acquisition_trials: int = 0
    acquisition_accepted: int = 0
    acquisition_rejected: int = 0
    contact_slot_ms: float = 0.0
    contact_slot_weight: float = DEFAULT_SLOT_WEIGHT
    local_energies: tuple = ()
    stationarity_history: tuple = ()
    reference_signature: str = ""


def solve_package8(request, snapshot=None, contact_weight=DEFAULT_SLOT_WEIGHT):
    started = perf_counter(); triangle = snapshot or p5.build_triangle_snapshot(request.colliders)
    planner = p5._package5_planner(request, triangle)
    if not planner.succeeded:
        return _failed(request, planner, started, contact_weight)
    state = p6._state(request, p5._solver_planner(request, planner), triangle, contact_weight)
    _initialize(state); _freeze_reference(state)
    termination, message = _iterate(state); return _finish(state, termination, message, started)


def _initialize(state):
    p5._prepare_contacts(state); state.acquisition_ms = 0.0
    state.acquisition_trials = state.acquisition_accepted = state.acquisition_rejected = 0
    state.slot_ms = 0.0; state.local_energies = []; state.stationarity_history = []
    state.slot_nodes = state.points.copy(); state.slot_edges = _midpoints(state.points, p5._cyclic(state))


def _freeze_reference(state):
    state.reference = state.points.copy(); state.accepted = []; state.rejected = state.trials = 0
    state.structural = solve_structural(state.reference, state.pins, state.request.settings).points.copy()
    state.active.clear(); state.active_edges.clear(); state.fixed_residual = float("inf")


def _remaining_budget(state):
    return max(1, state.request.settings.max_accepted_steps - state.acquisition_accepted)


def _iterate(state):
    budget = _remaining_budget(state)
    for _trial in range(budget):
        state.trials += 1; candidate = _candidate(state); changed = state.contact_changed
        accepted, full, step = _accept(state, candidate)
        terminal = _terminal(state, accepted, full, changed, step)
        if terminal is not None:
            return terminal
    return V2Termination.BUDGET_EXHAUSTED, "fixed contact-slot accepted-step cap exhausted"


def _candidate(state):
    started = perf_counter(); prior = set(state.active_edges); selected = _contact_targets(state)
    state.slot_active = bool(selected)
    state.contact_changed = prior != set(state.active_edges)
    candidate = state.structural.copy() if not selected else _slot_candidate(state)
    state.slot_ms += p5._elapsed(started)
    return p5._record_candidate(state, candidate)


def _contact_targets(state):
    edges = p6._edges(state); query = p5._contact_query_rows(state, state.structural, edges)
    rows = _contact_batch(state, query); p5._store_exact_contacts(state, edges, query[2], rows)
    selected = _selected_contacts(query[2], rows)
    state.slot_nodes = state.points.copy(); state.slot_edges = _midpoints(state.points, p5._cyclic(state))
    _apply_contact_targets(state, selected, edges)
    return selected


def _contact_batch(state, query):
    if not state.request.colliders:
        return _empty_contacts(len(query[1]))
    radius = state.request.collision_policy.collision_radius; slack = state.request.tolerances.clearance_slack
    band = max(0.5 * radius, 2.0 * slack); world = p5.cached_native_collision_world(state.request.colliders)
    return world.contacts(query[0], query[1], (("", ""),) * len(query[1]), 0.0,
                          radius + band - slack, query[3], query[4])


def _empty_contacts(count):
    from .collision import V2ContactBatch
    shape = (int(count),); zeros = np.zeros(shape, dtype=np.float64)
    return V2ContactBatch(tuple(False for _ in range(count)), zeros, np.zeros((count, 3)),
                          np.zeros((count, 3)), np.full(count, np.inf), tuple("" for _ in range(count)), 0, 0, np.inf)


def _selected_contacts(mapping, rows):
    selected = {}
    for index, active in enumerate(rows.active):
        if not active:
            continue
        edge, low, high = mapping[index]; factor = low + (high - low) * rows.factors[index]
        value = (float(rows.distances[index]), float(factor), rows.normals[index], rows.closest[index])
        if edge not in selected or value[0] < selected[edge][0]:
            selected[int(edge)] = value
    return selected


def _apply_contact_targets(state, selected, edges):
    threshold = state.request.collision_policy.collision_radius - state.request.tolerances.clearance_slack
    probe_midpoints = _midpoints(state.structural, p5._cyclic(state))
    for edge, (distance, factor, normal, closest) in selected.items():
        if distance >= threshold:
            continue
        first, second = edges[edge]; sample = (1.0 - factor) * state.structural[first] + factor * state.structural[second]
        target = np.asarray(closest) + max(0.0, threshold) * np.asarray(normal)
        state.slot_edges[edge] = probe_midpoints[edge] + target - sample


def _slot_candidate(state):
    started = perf_counter()
    result = solve_contact_structural(state.reference, state.points, state.slot_nodes,
                                      state.slot_edges, state.pins, state.request.settings,
                                      state.contact_weight, state.contact_weight)
    state.solve_ms += p5._elapsed(started); state.slot_stationarity = result.stationarity_residual
    return result.points.copy()


def _accept(state, candidate):
    envelope = p5._waypoint_envelope(state.points, (candidate,)); started = perf_counter()
    step = p5._safe_step_p51(state, state.points, candidate, envelope)
    state.ccd_ms += p5._elapsed(started); p5._absorb_ccd(state, step)
    proposed, full = p5._ccd_proposal(state.points, candidate, step)
    if proposed is None:
        state.rejected += 1; return False, False, step
    return (*_accept_local(state, proposed, full), step)


def _accept_local(state, proposed, full):
    current, merit = _local_merit(state, state.points), _local_merit(state, proposed)
    if merit > current + 1.0e-12 * max(1.0, current):
        state.rejected += 1; return False, False
    prior = state.points.copy(); state.last_step = p5._normalized_step(state, proposed)
    state.points = np.asarray(proposed); state.accepted.append(float(merit)); state.local_energies.append(float(merit))
    state.stationarity_history.append(_stationarity(state)); state.distance_cache.advance(p6._edges(state), prior, state.points)
    return True, bool(full)


def _local_merit(state, points):
    if not state.slot_active:
        return float(structural_energy(points, state.reference, state.request.settings).total)
    energy = contact_slot_energy(points, state.reference, state.slot_nodes, state.slot_edges,
                                 state.request.settings, state.contact_weight, state.contact_weight)
    return float(energy.total)


def _stationarity(state):
    if not state.slot_active:
        gradient = structural_gradient(state.points, state.reference, state.pins, state.request.settings)
        return _scaled_stationarity(state, gradient)
    value = contact_stationarity(state.points, state.reference, state.slot_nodes, state.slot_edges,
                                 state.pins, state.request.settings, state.contact_weight, state.contact_weight)
    return _scaled_stationarity(state, value)


def _scaled_stationarity(state, value):
    scale = max(state.request.tolerances.length_scale, 1.0e-12)
    if np.isscalar(value):
        return float(value / scale)
    return float(np.max(np.linalg.norm(value, axis=1)) / scale) if len(value) else 0.0


def _terminal(state, accepted, full, changed, step):
    if not step.valid and step.reason.value == "BACKEND_UNAVAILABLE":
        return V2Termination.BACKEND_UNAVAILABLE, "native collision backend unavailable"
    if accepted and full and not state.slot_active:
        return V2Termination.CONVERGED, "clear fixed-reference structural solution"
    tolerance = state.request.tolerances
    if accepted and full and not changed and state.fixed_residual <= tolerance.fixed_point_tolerance and _stationarity(state) <= tolerance.stationarity_tolerance:
        return V2Termination.CONVERGED, "fixed contact-slot local/global fixed point"
    if not accepted and not changed:
        return V2Termination.BLOCKED, "fixed contact-slot step is CCD or merit blocked"
    return None


def _finish(state, termination, message, started):
    checked = p5._timed_validation(state, state.points); diagnostics = _diagnostics(state, checked)
    validated = bool(checked.valid and np.isfinite(state.points).all())
    if not validated:
        termination, message = V2Termination.UNSAFE_OUTPUT, "final independent validation failed"
    result = p5._result(state.request, state.planner, state.points, diagnostics,
                        termination, validated, message, V2_SOLVER_P8_VERSION)
    return p5.V2Package5Result(result, state.planner, _trace(state, started))


def _diagnostics(state, checked):
    energy = structural_energy(state.points, state.reference, state.request.settings)
    accepted = state.acquisition_accepted + len(state.accepted); rejected = state.acquisition_rejected + state.rejected
    return V2Diagnostics(energy.fidelity, energy.length, energy.curvature, p5._contact_energy(state, checked),
                         state.fixed_residual, _stationarity(state), checked.node_residual,
                         checked.edge_residual, state.fractions[-1] if state.fractions else 1.0,
                         state.ccd_pairs, state.ccd_tested, accepted, rejected, 0)


def _trace(state, started):
    base = p5._trace(state, started)
    return V2Package8Trace(**vars(base), acquisition_ms=float(state.acquisition_ms),
                           acquisition_trials=state.acquisition_trials,
                           acquisition_accepted=state.acquisition_accepted,
                           acquisition_rejected=state.acquisition_rejected,
                           contact_slot_ms=float(state.slot_ms), contact_slot_weight=float(state.contact_weight),
                           local_energies=tuple(state.local_energies),
                           stationarity_history=tuple(state.stationarity_history),
                           reference_signature=_signature(state.reference))


def _midpoints(points, cyclic):
    count = len(points) if cyclic else len(points) - 1; indices = np.arange(count, dtype=np.int64)
    return 0.5 * (np.asarray(points)[indices] + np.asarray(points)[(indices + 1) % len(points)])


def _signature(points):
    return sha256(np.asarray(points, dtype=np.float64).tobytes()).hexdigest()


def _failed(request, planner, started, contact_weight):
    result = p5._result(request, planner, (), V2Diagnostics(), planner.termination, False,
                        planner.message, V2_SOLVER_P8_VERSION)
    trace = V2Package8Trace(total_ms=p5._elapsed(started), contact_weight=float(contact_weight),
                            contact_slot_weight=float(contact_weight))
    return p5.V2Package5Result(result, planner, trace)
