"""Package 8.1 fixed multi-sample contact-slot Fiber V2 experiment."""

from dataclasses import dataclass
from time import perf_counter

import numpy as np

from .contact_sampled import (DEFAULT_SAMPLE_FACTORS, sample_edge_points,
                              sampled_contact_energy, sampled_contact_stationarity,
                              solve_sampled_contact)
from .contracts import V2Diagnostics, V2Termination
from .structural import structural_energy, structural_gradient
from . import solver as p5
from . import solver_p6 as p6
from . import solver_p8 as p8


V2_SOLVER_P81_VERSION = "fiber-v2-solver-package8.1-1"


@dataclass(frozen=True)
class V2Package81Trace(p8.V2Package8Trace):
    sample_factors: tuple = DEFAULT_SAMPLE_FACTORS
    contact_query_rows: int = 0
    sample_contact_counts: tuple = ()
    distinct_blocker_counts: tuple = ()


def solve_package81(request, snapshot=None, contact_weight=p8.DEFAULT_SLOT_WEIGHT,
                    sample_factors=DEFAULT_SAMPLE_FACTORS):
    started = perf_counter(); triangle = snapshot or p5.build_triangle_snapshot(request.colliders)
    planner = p5._package5_planner(request, triangle)
    if not planner.succeeded:
        return _failed(request, planner, started, contact_weight, sample_factors)
    state = p6._state(request, p5._solver_planner(request, planner), triangle, contact_weight)
    _initialize(state, sample_factors); p8._freeze_reference(state)
    termination, message = _iterate(state); return _finish(state, termination, message, started)


def _initialize(state, sample_factors):
    p8._initialize(state); state.sample_factors = tuple(float(value) for value in sample_factors)
    state.sample_targets = sample_edge_points(state.points, state.sample_factors, state.request.settings)
    state.slot_keys = set(); state.contact_query_rows = 0
    state.sample_contact_counts = []; state.distinct_blocker_counts = []


def _iterate(state):
    for _trial in range(p8._remaining_budget(state)):
        state.trials += 1; candidate = _candidate(state); changed = state.contact_changed
        accepted, full, step = _accept(state, candidate)
        terminal = _terminal(state, accepted, full, changed, step)
        if terminal is not None:
            return terminal
    return V2Termination.BUDGET_EXHAUSTED, "multi-sample contact-slot accepted-step cap exhausted"


def _candidate(state):
    started = perf_counter(); prior = set(state.slot_keys); selected = _contact_targets(state)
    state.slot_active = bool(selected); state.contact_changed = prior != state.slot_keys
    candidate = state.structural.copy() if not selected else _slot_candidate(state)
    state.slot_ms += p5._elapsed(started)
    return p5._record_candidate(state, candidate)


def _contact_targets(state):
    edges = p6._edges(state); query = _sample_query_rows(state, state.structural, edges)
    rows = p8._contact_batch(state, query); selected = _selected_contacts(query[2], rows)
    state.contact_query_rows += len(query[1]); state.sample_targets = sample_edge_points(
        state.points, state.sample_factors, state.request.settings)
    _store_contacts(state, edges, selected); _apply_targets(state, selected, edges)
    state.sample_contact_counts.append(len(selected)); _store_blocker_count(state, selected)
    return selected


def _sample_query_rows(state, points, edges):
    rows, mapping, only, skip = [], [], [], []
    for edge, nodes in enumerate(edges):
        contacts = p5._edge_contact_intervals(state.planner.contacts, edge)
        for slot, bounds in enumerate(_sample_bins(state.sample_factors)):
            _append_sample_rows(rows, mapping, only, skip, points[nodes], edge, slot, bounds, contacts)
    values = np.asarray(rows, dtype=np.float64).reshape((-1, 2, 3))
    links = np.arange(len(rows) * 2, dtype=np.int64).reshape((-1, 2))
    return values.reshape((-1, 3)), links, tuple(mapping), tuple(only), tuple(skip)


def _sample_bins(factors):
    values = np.asarray(factors, dtype=np.float64)
    bounds = np.concatenate(([0.0], 0.5 * (values[:-1] + values[1:]), [1.0]))
    return tuple((float(bounds[index]), float(bounds[index + 1])) for index in range(len(values)))


def _append_sample_rows(rows, mapping, only, skip, points, edge, slot, bounds, contacts):
    low, high = bounds; owners = tuple(dict.fromkeys(owner for owner, _a, _b in contacts))
    if len(owners) != 1:
        _append_row(rows, mapping, only, skip, points, edge, slot, low, high, "", ""); return
    owner = owners[0]; _append_row(rows, mapping, only, skip, points, edge, slot, low, high, "", owner)
    for start, end in p5._remaining_intervals(contacts):
        _append_intersection(rows, mapping, only, skip, points, edge, slot, low, high, start, end, owner)


def _append_intersection(rows, mapping, only, skip, points, edge, slot, low, high, start, end, owner):
    first, second = max(low, start), min(high, end)
    if first < second:
        _append_row(rows, mapping, only, skip, points, edge, slot, first, second, owner, "")


def _append_row(rows, mapping, only, skip, points, edge, slot, low, high, include, exclude):
    delta = np.asarray(points[1]) - points[0]
    rows.append((points[0] + low * delta, points[0] + high * delta))
    mapping.append((edge, slot, low, high)); only.append(include); skip.append(exclude)


def _selected_contacts(mapping, rows):
    selected = {}
    for index, active in enumerate(rows.active):
        if active:
            edge, slot, low, high = mapping[index]; factor = low + (high - low) * rows.factors[index]
            value = (float(rows.distances[index]), float(factor), rows.normals[index],
                     rows.closest[index], rows.blockers[index])
            if (edge, slot) not in selected or value[0] < selected[(edge, slot)][0]:
                selected[(int(edge), int(slot))] = value
    return selected


def _store_contacts(state, edges, selected):
    state.active_edges = {edge for edge, _slot in selected}
    state.active = {int(node) for edge in state.active_edges for node in edges[edge]}
    state.slot_keys = {(edge, slot, row[4]) for (edge, slot), row in selected.items()}
    state.contact_rows = [p5._native_contact_row(edges[edge], row[1], row[2])
                          for (edge, _slot), row in sorted(selected.items())]
    _store_normals(state, edges, selected); state.active_counts.append(len(state.active))


def _store_normals(state, edges, selected):
    state.normals.fill(0.0)
    for (edge, _slot), (_distance, factor, normal, _closest, _blocker) in selected.items():
        first, second = edges[edge]; state.normals[first] += (1.0 - factor) * normal
        state.normals[second] += factor * normal
    lengths = np.linalg.norm(state.normals, axis=1); mask = lengths > 1.0e-12
    state.normals[mask] /= lengths[mask, None]


def _store_blocker_count(state, selected):
    blockers = {row[4] for row in selected.values() if row[4]}
    state.distinct_blocker_counts.append(len(blockers))


def _apply_targets(state, selected, edges):
    threshold = state.request.collision_policy.collision_radius - state.request.tolerances.clearance_slack
    probe = sample_edge_points(state.structural, state.sample_factors, state.request.settings)
    for (edge, slot), (distance, factor, normal, closest, _blocker) in selected.items():
        if distance < threshold:
            _apply_target(state, probe, edges, edge, slot, factor, normal, closest, threshold)


def _apply_target(state, probe, edges, edge, slot, factor, normal, closest, threshold):
    first, second = edges[edge]
    actual = (1.0 - factor) * state.structural[first] + factor * state.structural[second]
    target = np.asarray(closest) + max(0.0, threshold) * np.asarray(normal)
    state.sample_targets[edge, slot] = probe[edge, slot] + target - actual


def _slot_candidate(state):
    started = perf_counter()
    result = solve_sampled_contact(state.reference, state.sample_targets, state.pins,
                                   state.request.settings, state.contact_weight, state.sample_factors)
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
    energy = sampled_contact_energy(points, state.reference, state.sample_targets,
                                    state.request.settings, state.contact_weight, state.sample_factors)
    return float(energy.total)


def _stationarity(state):
    if not state.slot_active:
        gradient = structural_gradient(state.points, state.reference, state.pins, state.request.settings)
        return p8._scaled_stationarity(state, gradient)
    value = sampled_contact_stationarity(state.points, state.reference, state.sample_targets,
                                         state.pins, state.request.settings,
                                         state.contact_weight, state.sample_factors)
    return p8._scaled_stationarity(state, value)


def _terminal(state, accepted, full, changed, step):
    if not step.valid and step.reason.value == "BACKEND_UNAVAILABLE":
        return V2Termination.BACKEND_UNAVAILABLE, "native collision backend unavailable"
    if accepted and full and not state.slot_active:
        return V2Termination.CONVERGED, "clear fixed-reference structural solution"
    tolerance = state.request.tolerances
    if accepted and full and not changed and state.fixed_residual <= tolerance.fixed_point_tolerance and _stationarity(state) <= tolerance.stationarity_tolerance:
        return V2Termination.CONVERGED, "fixed multi-sample contact-slot local/global fixed point"
    if not accepted and not changed:
        return V2Termination.BLOCKED, "multi-sample contact-slot step is CCD or merit blocked"
    return None


def _finish(state, termination, message, started):
    checked = p5._timed_validation(state, state.points); diagnostics = _diagnostics(state, checked)
    validated = bool(checked.valid and np.isfinite(state.points).all())
    if not validated:
        termination, message = V2Termination.UNSAFE_OUTPUT, "final independent validation failed"
    result = p5._result(state.request, state.planner, state.points, diagnostics,
                        termination, validated, message, V2_SOLVER_P81_VERSION)
    return p5.V2Package5Result(result, state.planner, _trace(state, started))


def _diagnostics(state, checked):
    energy = structural_energy(state.points, state.reference, state.request.settings)
    accepted = state.acquisition_accepted + len(state.accepted); rejected = state.acquisition_rejected + state.rejected
    return V2Diagnostics(energy.fidelity, energy.length, energy.curvature, p5._contact_energy(state, checked),
                         state.fixed_residual, _stationarity(state), checked.node_residual,
                         checked.edge_residual, state.fractions[-1] if state.fractions else 1.0,
                         state.ccd_pairs, state.ccd_tested, accepted, rejected, 0)


def _trace(state, started):
    base = p8._trace(state, started)
    return V2Package81Trace(**vars(base), sample_factors=state.sample_factors,
                            contact_query_rows=state.contact_query_rows,
                            sample_contact_counts=tuple(state.sample_contact_counts),
                            distinct_blocker_counts=tuple(state.distinct_blocker_counts))


def _failed(request, planner, started, contact_weight, sample_factors):
    result = p5._result(request, planner, (), V2Diagnostics(), planner.termination, False,
                        planner.message, V2_SOLVER_P81_VERSION)
    trace = V2Package81Trace(total_ms=p5._elapsed(started), contact_weight=float(contact_weight),
                             contact_slot_weight=float(contact_weight),
                             sample_factors=tuple(float(value) for value in sample_factors))
    return p5.V2Package5Result(result, planner, trace)
