"""Package 8.2 unilateral active-contact Fiber V2 experiment."""

from dataclasses import dataclass
from time import perf_counter

import numpy as np

from .contact_unilateral import UnilateralConstraint, solve_unilateral_contact
from .contracts import V2Diagnostics, V2Termination
from .structural import structural_energy, structural_gradient
from . import solver as p5
from . import solver_p6 as p6
from . import solver_p8 as p8
from . import solver_p81 as p81


V2_SOLVER_P82_VERSION = "fiber-v2-solver-package8.2-1"


@dataclass(frozen=True)
class V2Package82Trace(p81.V2Package81Trace):
    qp_ms: float = 0.0
    qp_iterations: tuple = ()
    qp_active_counts: tuple = ()
    qp_primal_residuals: tuple = ()
    qp_stationarity_residuals: tuple = ()


def solve_package82(request, snapshot=None, sample_factors=p81.DEFAULT_SAMPLE_FACTORS):
    started = perf_counter(); triangle = snapshot or p5.build_triangle_snapshot(request.colliders)
    planner = p5._package5_planner(request, triangle)
    if not planner.succeeded:
        return _failed(request, planner, started, sample_factors)
    state = p6._state(request, p5._solver_planner(request, planner), triangle, p8.DEFAULT_SLOT_WEIGHT)
    _initialize(state, sample_factors); p8._freeze_reference(state)
    termination, message = _iterate(state); return _finish(state, termination, message, started)


def _initialize(state, factors):
    p81._initialize(state, factors); state.qp_ms = 0.0; state.qp_result = None
    state.qp_iterations = []; state.qp_active_counts = []; state.qp_primal_residuals = []
    state.qp_stationarity_residuals = []; state.constraint_signature = (); state.constraint_pool = {}; state.qp_hint = ()


def _iterate(state):
    for _trial in range(p8._remaining_budget(state)):
        state.trials += 1; candidate = _candidate(state); changed = state.contact_changed
        accepted, full, step = _accept(state, candidate); terminal = _terminal(state, accepted, full, changed, step)
        if terminal is not None:
            return terminal
    return V2Termination.BUDGET_EXHAUSTED, "unilateral active-contact accepted-step cap exhausted"


def _candidate(state):
    selected = _contact_rows(state); constraints = _constraints(state, selected)
    _extend_pool(state, constraints); candidate = _qp_candidate(state, tuple(state.constraint_pool.values()))
    candidate = _refine_candidate_contacts(state, candidate); signature = tuple(state.constraint_pool)
    state.contact_changed = signature != state.constraint_signature; state.constraint_signature = signature
    _limit_contact_trust(state, constraints)
    candidate, state.qp_clipped = p6._bounded_candidate(state, candidate)
    return p5._record_candidate(state, candidate)


def _limit_contact_trust(state, constraints):
    if constraints:
        radius = state.request.collision_policy.collision_radius
        state.trust_radius = min(state.trust_radius, max(0.5 * radius, state.min_trust))


def _extend_pool(state, constraints):
    before = len(state.constraint_pool)
    for row in constraints:
        state.constraint_pool.setdefault(_row_signature(row), row)
    return len(state.constraint_pool) - before


def _refine_candidate_contacts(state, candidate):
    edges = p6._edges(state)
    for _iteration in range(3):
        selected = [(edge, slot, value) for (edge, slot), value in _query(state, candidate, edges).items()]
        if not _extend_pool(state, _constraints(state, selected)):
            break
        candidate = _qp_candidate(state, tuple(state.constraint_pool.values()))
    return candidate


def _contact_rows(state):
    edges = p6._edges(state); current = _query(state, state.points, edges)
    structural = _query(state, state.structural, edges); display = dict(structural); display.update(current)
    p81._store_contacts(state, edges, display); combined = _combined_rows(current, structural)
    state.sample_contact_counts.append(len(combined)); p81._store_blocker_count(state, display)
    return combined


def _combined_rows(current, structural):
    rows = [(edge, slot, value) for (edge, slot), value in current.items()]
    rows += [(edge, slot, value) for (edge, slot), value in structural.items()]
    return tuple(rows)


def _query(state, points, edges):
    started = perf_counter(); query = p81._sample_query_rows(state, points, edges)
    rows = p8._contact_batch(state, query); state.contact_query_ms += p5._elapsed(started)
    state.contact_query_rows += len(query[1]); return p81._selected_contacts(query[2], rows)


def _constraints(state, selected):
    edges = p6._edges(state); threshold = _threshold(state); rows = []
    for edge, slot, value in sorted(selected, key=lambda row: (row[0], row[1], row[2][4])):
        constraint = _constraint(state.points, edges[edge], value, threshold, f"{edge}:{slot}:{value[4]}")
        if constraint is not None:
            rows.append(constraint)
    return tuple(rows)


def _constraint(points, nodes, value, threshold, tag):
    _distance, factor, normal, closest, _blocker = value; normal = np.asarray(normal, dtype=np.float64)
    length = float(np.linalg.norm(normal))
    if not np.isfinite(length) or length <= 1.0e-12:
        return None
    normal /= length; sample = (1.0 - factor) * points[nodes[0]] + factor * points[nodes[1]]
    if float(np.dot(normal, sample - closest)) < 0.0:
        normal = -normal
    offset = min(float(np.dot(normal, closest) + threshold), float(np.dot(normal, sample)))
    return UnilateralConstraint(tuple(nodes), (1.0 - factor, factor), tuple(normal), offset, tag)


def _threshold(state):
    return max(0.0, state.request.collision_policy.collision_radius - state.request.tolerances.clearance_slack)


def _row_signature(row):
    weights = tuple(round(value, 8) for value in row.weights)
    normal = tuple(round(value, 8) for value in row.normal)
    return row.tag, row.nodes, weights, normal, round(row.offset, 8)


def _qp_candidate(state, constraints):
    started = perf_counter()
    result = solve_unilateral_contact(state.reference, constraints, state.pins, state.request.settings,
                                      tolerance=max(state.request.tolerances.numeric_floor, 1.0e-10),
                                      active_hint=state.qp_hint)
    elapsed = p5._elapsed(started); state.qp_result = result; state.qp_ms += elapsed; state.solve_ms += elapsed
    state.qp_hint = result.active_indices
    state.qp_iterations.append(result.iterations); state.qp_active_counts.append(len(result.active_indices))
    state.qp_primal_residuals.append(result.primal_residual)
    state.qp_stationarity_residuals.append(_scaled(state, result.stationarity_residual))
    state.slot_active = bool(constraints); return result.points.copy()


def _accept(state, candidate):
    envelope = p5._waypoint_envelope(state.points, (candidate,)); started = perf_counter()
    step = p5._safe_step_p51(state, state.points, candidate, envelope)
    state.ccd_ms += p5._elapsed(started); p5._absorb_ccd(state, step)
    proposed, full = p5._ccd_proposal(state.points, candidate, step)
    if proposed is None:
        state.rejected += 1; p6._update_trust(state, False, False, step); return False, False, step
    accepted, full = _accept_local(state, proposed, full)
    p6._update_trust(state, accepted, full, step); return accepted, full, step


def _accept_local(state, proposed, full):
    current = structural_energy(state.points, state.reference, state.request.settings).total
    merit = structural_energy(proposed, state.reference, state.request.settings).total
    if merit > current + 1.0e-12 * max(1.0, current):
        state.rejected += 1; return False, False
    prior = state.points.copy(); state.last_step = p5._normalized_step(state, proposed)
    state.points = np.asarray(proposed); state.accepted.append(float(merit)); state.local_energies.append(float(merit))
    state.distance_cache.advance(p6._edges(state), prior, state.points); return True, bool(full)


def _terminal(state, accepted, full, changed, step):
    if not step.valid and step.reason.value == "BACKEND_UNAVAILABLE":
        return V2Termination.BACKEND_UNAVAILABLE, "native collision backend unavailable"
    if state.qp_result is not None and not state.qp_result.feasible:
        return V2Termination.BLOCKED, "linearized unilateral contact system is infeasible"
    if accepted and full and _converged(state, changed):
        return V2Termination.CONVERGED, "unilateral active-contact KKT fixed point"
    if not accepted and not changed:
        return V2Termination.BLOCKED, "unilateral active-contact step is CCD blocked"
    return None


def _converged(state, changed):
    tolerance = state.request.tolerances
    if not state.slot_active:
        return True
    stationarity = state.qp_stationarity_residuals[-1] if state.qp_stationarity_residuals else float("inf")
    return not state.qp_clipped and not changed and state.fixed_residual <= tolerance.fixed_point_tolerance and stationarity <= tolerance.stationarity_tolerance


def _scaled(state, value):
    return float(value) / max(state.request.tolerances.length_scale, 1.0e-12)


def _finish(state, termination, message, started):
    checked = p5._timed_validation(state, state.points); diagnostics = _diagnostics(state, checked)
    validated = bool(checked.valid and np.isfinite(state.points).all())
    if not validated:
        termination, message = V2Termination.UNSAFE_OUTPUT, "final independent validation failed"
    result = p5._result(state.request, state.planner, state.points, diagnostics,
                        termination, validated, message, V2_SOLVER_P82_VERSION)
    return p5.V2Package5Result(result, state.planner, _trace(state, started))


def _diagnostics(state, checked):
    energy = structural_energy(state.points, state.reference, state.request.settings)
    accepted = state.acquisition_accepted + len(state.accepted); rejected = state.acquisition_rejected + state.rejected
    stationarity = state.qp_stationarity_residuals[-1] if state.qp_stationarity_residuals else _clear_stationarity(state)
    return V2Diagnostics(energy.fidelity, energy.length, energy.curvature, p5._contact_energy(state, checked),
                         state.fixed_residual, stationarity, checked.node_residual, checked.edge_residual,
                         state.fractions[-1] if state.fractions else 1.0, state.ccd_pairs, state.ccd_tested,
                         accepted, rejected, 0)


def _clear_stationarity(state):
    gradient = structural_gradient(state.points, state.reference, state.pins, state.request.settings)
    return p8._scaled_stationarity(state, gradient)


def _trace(state, started):
    base = p81._trace(state, started)
    return V2Package82Trace(**vars(base), qp_ms=float(state.qp_ms), qp_iterations=tuple(state.qp_iterations),
                            qp_active_counts=tuple(state.qp_active_counts),
                            qp_primal_residuals=tuple(state.qp_primal_residuals),
                            qp_stationarity_residuals=tuple(state.qp_stationarity_residuals))


def _failed(request, planner, started, factors):
    result = p5._result(request, planner, (), V2Diagnostics(), planner.termination, False,
                        planner.message, V2_SOLVER_P82_VERSION)
    trace = V2Package82Trace(total_ms=p5._elapsed(started), sample_factors=tuple(factors))
    return p5.V2Package5Result(result, planner, trace)
