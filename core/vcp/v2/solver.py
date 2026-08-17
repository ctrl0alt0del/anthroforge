"""Package 5 unaccelerated, Blender-independent Fiber V2 solver."""

from dataclasses import dataclass, replace
from time import perf_counter

import numpy as np

from .collision import (build_triangle_snapshot, cached_native_collision_world,
                        collision_backend_status, collision_free_step, V2SweepPairCache,
                        validate_static_clearance)
from .contracts import V2Diagnostics, V2Result, V2Termination, V2Topology
from .planner import V2PlannerResult, _anchor_contact, plan_reference_v43
from .structural import solve_structural, structural_energy, structural_gradient


V2_SOLVER_P5_VERSION = "fiber-v2-solver-package5-2"
V2_SOLVER_P51_VERSION = "fiber-v2-solver-package5.1-1"
DEFAULT_CONTACT_WEIGHT = 1000.0
PROXIMAL_WEIGHT = 0.05


@dataclass(frozen=True)
class V2Package5Trace:
    planner_ms: float = 0.0
    solve_ms: float = 0.0
    ccd_ms: float = 0.0
    validation_ms: float = 0.0
    contact_weight: float = DEFAULT_CONTACT_WEIGHT
    trials: int = 0
    accepted_merits: tuple = ()
    ccd_fractions: tuple = ()
    active_counts: tuple = ()
    projection_scale: float = 1.0
    candidate_ms: float = 0.0
    total_ms: float = 0.0
    contact_query_ms: float = 0.0
    static_validations: int = 0
    pair_cache_hits: int = 0
    pair_cache_misses: int = 0
    curved_waypoints: int = 0


@dataclass(frozen=True)
class V2Package5Result:
    result: V2Result
    planner: V2PlannerResult
    trace: V2Package5Trace

    @property
    def succeeded(self):
        return self.result.successful


@dataclass
class _SolverState:
    request: object
    planner: object
    snapshot: object
    reference: np.ndarray
    pins: dict
    points: np.ndarray
    structural: np.ndarray
    projections: np.ndarray
    normals: np.ndarray
    contact_weight: float
    active: set
    active_edges: set
    contact_rows: list
    accepted: list
    fractions: list
    active_counts: list
    rejected: int = 0
    ccd_pairs: int = 0
    ccd_tested: int = 0
    solve_ms: float = 0.0
    ccd_ms: float = 0.0
    validation_ms: float = 0.0
    projection_scale: float = 1.0
    last_step: float = float("inf")
    contact_changed: bool = False
    fixed_residual: float = float("inf")
    trials: int = 0
    candidate_ms: float = 0.0
    optimized: bool = False
    pair_cache: object = None
    contact_query_ms: float = 0.0
    static_validations: int = 0
    curved_waypoints: int = 0
    native_world: object = None


def solve_package5(request, snapshot=None, contact_weight=DEFAULT_CONTACT_WEIGHT):
    return _solve_package5(request, snapshot, contact_weight, False)


def solve_package51(request, snapshot=None, contact_weight=DEFAULT_CONTACT_WEIGHT):
    return _solve_package5(request, snapshot, contact_weight, True)


def _solve_package5(request, snapshot, contact_weight, optimized):
    started = perf_counter(); triangle = snapshot or build_triangle_snapshot(request.colliders)
    planner = _package5_planner(request, triangle)
    if not planner.succeeded:
        return _failed(request, planner, started, contact_weight, optimized)
    planner = _solver_planner(request, planner)
    state = _solver_state(request, planner, triangle, contact_weight, optimized)
    _prepare_contacts(state)
    termination, message = _iterate(state)
    return _finish(state, termination, message, started)


def _package5_planner(request, snapshot):
    planner = plan_reference_v43(request, snapshot)
    if planner.succeeded and planner.mode.value == "ROADMAP":
        updated = plan_reference_v43(request, snapshot, owner_contact_factor=8.0)
        diagnostics = _merged_planner_diagnostics(planner, updated)
        planner = replace(updated, diagnostics=diagnostics)
    return planner


def _merged_planner_diagnostics(first, second):
    a, b = first.diagnostics, second.diagnostics
    return replace(b, planner_ms=a.planner_ms + b.planner_ms,
                   handoff_ms=a.handoff_ms + b.handoff_ms)


def _solver_state(request, planner, snapshot, contact_weight, optimized=False):
    weight = _contact_weight(contact_weight); reference = np.asarray(planner.reference, dtype=np.float64)
    pins = {int(index): anchor.point for index, anchor in zip(planner.pin_indices, request.anchors)}
    points = _initial_points(request, planner, snapshot, reference, pins)
    structural = points.copy()
    state = _SolverState(request, planner, snapshot, reference, pins, points, structural,
                          structural.copy(), np.zeros_like(reference),
                          weight, set(), set(), [], [], [], [])
    state.optimized = bool(optimized); state.pair_cache = V2SweepPairCache() if optimized else None
    return state


def _solver_planner(request, planner):
    if planner.mode.value != "ROADMAP":
        return planner
    span = max(8.0 * request.collision_policy.collision_radius, 1.0e-7)
    cyclic = request.settings.topology is V2Topology.CYCLIC
    contacts = tuple(_anchor_contact(planner.reference, int(index), anchor.owner_id, span, cyclic)
                     for index, anchor in zip(planner.pin_indices, request.anchors) if anchor.owner_id)
    return replace(planner, contacts=contacts)


def _contact_weight(value):
    weight = float(value)
    if not np.isfinite(weight) or weight <= 0.0:
        raise ValueError("contact weight must be finite and positive")
    return weight


def _initial_points(request, planner, snapshot, reference, pins):
    return reference.copy()


def _iterate(state):
    for _trial in range(state.request.settings.max_accepted_steps):
        state.trials += 1
        candidate = _candidate(state)
        if not state.optimized:
            _timed_validation(state, candidate)
        changed = state.contact_changed
        accepted, full = _accept_candidate(state, candidate)
        if accepted and full and not changed and _step_converged(state):
            return V2Termination.CONVERGED, "unaccelerated local/global fixed point"
        if not accepted and not changed:
            return V2Termination.BLOCKED, "contact set and CCD step are blocked"
    return V2Termination.BUDGET_EXHAUSTED, "accepted-step cap exhausted"


def _candidate(state):
    started = perf_counter(); result = _candidate_value(state)
    state.candidate_ms += _elapsed(started); return result


def _candidate_value(state):
    if state.optimized:
        return _candidate_value_p51(state)
    state.contact_changed, checked = _refresh_contacts(state)
    state.structural = _base_candidate(state)
    if state.planner.mode.value == "SURFACE":
        return _record_candidate(state, _surface_candidate(state))
    if not state.active:
        return _record_candidate(state, state.structural)
    _prepare_active_geometry(state, state.points, checked)
    return _record_candidate(state, _metric_project(state, state.structural))


def _candidate_value_p51(state):
    state.structural = _base_candidate(state)
    if state.planner.mode.value == "SURFACE":
        state.contact_changed = False; _clear_native_contacts(state)
        return _record_candidate(state, _surface_candidate(state))
    candidate = state.structural
    state.contact_changed = _refresh_native_contacts(state)
    candidate = _metric_project(state, candidate) if state.active else candidate
    return _record_candidate(state, candidate)


def _record_candidate(state, candidate):
    scale = max(state.request.tolerances.length_scale, 1.0e-12)
    delta = np.linalg.norm(np.asarray(candidate) - state.points, axis=1)
    state.fixed_residual = float(np.max(delta) / scale)
    return candidate


def _surface_candidate(state):
    return _surface_retract(state, state.structural)


def _surface_retract(state, points):
    owner = _surface_owner(state.request); colliders = _owner_colliders(state.request, owner)
    if not owner or not colliders:
        return np.asarray(points).copy()
    closest, normals, distances, _ids, contained = _collision_world(state, colliders).nearest(points)
    directions = _contact_directions(points, closest, normals, distances, contained)
    output = closest + 1.5 * state.request.collision_policy.collision_radius * directions
    _restore_pins(output, state.pins); return output


def _surface_owner(request):
    owners = {anchor.owner_id for anchor in request.anchors if anchor.owner_id}
    return next(iter(owners)) if len(owners) == 1 else ""


def _owner_colliders(request, owner):
    return tuple(collider for collider in request.colliders if collider.owner_id == owner)


def _edge_nodes(edge, count, cyclic):
    return edge, (edge + 1) % count if cyclic else min(edge + 1, count - 1)


def _accept_candidate(state, candidate):
    if state.optimized:
        return _accept_curved(state, candidate)
    before = perf_counter(); step = _safe_step(state, candidate)
    state.ccd_ms += _elapsed(before); _absorb_ccd(state, step)
    if not step.valid or step.safe_step <= 1.0e-12:
        state.rejected += 1; return False, False
    return _accept_fractions(state, candidate, step.safe_step)


def _accept_curved(state, candidate):
    waypoints = _curved_waypoints(state, candidate); envelope = _waypoint_envelope(state.points, waypoints)
    if len(waypoints) > 1:
        return _accept_waypoints(state, waypoints, envelope)
    return _accept_direct(state, candidate, envelope)


def _accept_direct(state, candidate, envelope):
    started = perf_counter(); direct = _safe_step_p51(state, state.points, candidate, envelope)
    state.ccd_ms += _elapsed(started); _absorb_ccd(state, direct)
    proposed, full = _ccd_proposal(state.points, candidate, direct)
    return _accept_unvalidated(state, proposed, full) if proposed is not None else _reject_step(state)


def _accept_waypoints(state, waypoints, envelope):
    source = state.points; state.curved_waypoints += len(waypoints)
    for index, target in enumerate(waypoints):
        started = perf_counter(); step = _safe_step_p51(state, source, target, envelope)
        state.ccd_ms += _elapsed(started); _absorb_ccd(state, step)
        proposed, full = _ccd_proposal(source, target, step)
        if proposed is None:
            state.rejected += 1; return False, False
        if not full:
            return _accept_unvalidated(state, proposed, False)
        source = target
    return _accept_unvalidated(state, source, True)


def _reject_step(state):
    state.rejected += 1
    return False, False


def _curved_waypoints(state, candidate):
    if state.planner.mode.value == "SURFACE" or not state.active:
        return (np.asarray(candidate),)
    rows = []
    for factor in (0.25, 0.5, 0.75, 1.0):
        point = _interpolate(state.points, candidate, factor)
        point += _curved_lift(state, factor); _restore_pins(point, state.pins); rows.append(point)
    return tuple(rows)


def _curved_lift(state, factor):
    radius = state.request.collision_policy.collision_radius
    return 2.0 * radius * np.sin(np.pi * float(factor)) * state.normals


def _waypoint_envelope(source, waypoints):
    rows = np.stack((np.asarray(source), *tuple(np.asarray(row) for row in waypoints)))
    return np.min(rows, axis=0), np.max(rows, axis=0)


def _ccd_proposal(source, target, step):
    if not step.valid or step.safe_step <= 1.0e-12:
        return None, False
    fraction = _backed_fraction(step.safe_step)
    return _interpolate(source, target, fraction), fraction >= 1.0 - 1.0e-12


def _accept_unvalidated(state, proposed, full):
    current = _merit(state, state.points); merit = _merit(state, proposed)
    if merit > current + 1.0e-12 * max(1.0, current):
        state.rejected += 1; return False, False
    state.last_step = _normalized_step(state, proposed); state.points = np.asarray(proposed)
    state.accepted.append(float(merit)); return True, bool(full)


def _safe_step(state, candidate):
    request = state.request; policy = request.collision_policy; tolerance = request.tolerances
    return collision_free_step(state.points, candidate, state.snapshot, policy.collision_radius,
                               state.planner.contacts, cyclic=_cyclic(state),
                               slack=tolerance.clearance_slack)


def _safe_step_p51(state, source, candidate, envelope):
    request = state.request; policy = request.collision_policy; tolerance = request.tolerances
    return collision_free_step(source, candidate, state.snapshot, policy.collision_radius,
                               state.planner.contacts, cyclic=_cyclic(state),
                               slack=tolerance.clearance_slack, pair_cache=state.pair_cache,
                               assume_initial_valid=True, pair_envelope=envelope)


def _absorb_ccd(state, step):
    state.fractions.append(float(step.safe_step))
    state.ccd_pairs += int(step.candidate_pairs)
    state.ccd_tested += int(step.tested_pairs)


def _backed_fraction(value):
    fraction = float(value)
    return fraction if fraction >= 1.0 else max(0.0, fraction * 0.999)


def _interpolate(start, end, fraction):
    return np.asarray(start) + float(fraction) * (np.asarray(end) - start)


def _accept_validated(state, proposed, checked, fraction):
    current = _merit(state, state.points); merit = _merit(state, proposed)
    tolerance = 1.0e-12 * max(1.0, current)
    if not checked.valid or merit > current + tolerance:
        state.rejected += 1; return False, False
    state.last_step = _normalized_step(state, proposed)
    state.points = proposed; state.accepted.append(float(merit))
    return True, fraction >= 1.0 - 1.0e-12


def _timed_validation(state, points):
    before = perf_counter(); result = _validate(points, state.request, state.planner, state.snapshot)
    state.validation_ms += _elapsed(before); state.static_validations += 1; return result


def _validate(points, request, planner, snapshot):
    policy, tolerance = request.collision_policy, request.tolerances
    return validate_static_clearance(points, snapshot, policy.collision_radius,
                                     planner.contacts, cyclic=_cyclic_request(request),
                                     slack=tolerance.clearance_slack)


def _restore_pins(points, pins):
    for index, target in pins.items():
        points[int(index)] = target


def _cyclic(state):
    return _cyclic_request(state.request)


def _cyclic_request(request):
    return request.settings.topology is V2Topology.CYCLIC


def _finish(state, termination, message, started):
    checked = _timed_validation(state, state.points); diagnostics = _diagnostics(state, checked)
    validated = bool(checked.valid and np.isfinite(state.points).all())
    if not validated:
        termination, message = V2Termination.UNSAFE_OUTPUT, "final independent validation failed"
    version = V2_SOLVER_P51_VERSION if state.optimized else V2_SOLVER_P5_VERSION
    result = _result(state.request, state.planner, state.points, diagnostics,
                     termination, validated, message, version)
    return V2Package5Result(result, state.planner, _trace(state, started))


def _diagnostics(state, checked):
    energy = structural_energy(state.points, state.points, state.request.settings)
    fixed = _fixed_residual(state); stationarity = _stationarity(state)
    contact = _contact_energy(state, checked)
    return V2Diagnostics(energy.fidelity, energy.length, energy.curvature, contact,
                         fixed, stationarity, checked.node_residual, checked.edge_residual,
                         state.fractions[-1] if state.fractions else 1.0,
                         state.ccd_pairs, state.ccd_tested, len(state.accepted), state.rejected, 0)


def _fixed_residual(state):
    return float(state.fixed_residual)


def _contact_geometry(state, candidate):
    if not state.request.colliders:
        return candidate.copy(), np.zeros_like(candidate), np.full(len(candidate), np.inf)
    world = _collision_world(state)
    closest, normals, distances, _blockers, contained = world.nearest(candidate)
    directions = _contact_directions(candidate, closest, normals, distances, contained)
    radius = state.request.collision_policy.collision_radius
    return np.asarray(closest + radius * directions), directions, np.asarray(distances)


def _prepare_contacts(state):
    state.active_counts.clear()


def _prepare_active_geometry(state, candidate, checked):
    state.projections, state.normals, _distances = _contact_geometry(state, candidate)
    state.contact_rows = _contact_rows(state, candidate, checked)


def _contact_energy(state, checked):
    residual = max(float(checked.node_residual), float(checked.edge_residual))
    return state.contact_weight * residual * residual


def _merit(state, points):
    energy = structural_energy(points, points, state.request.settings)
    return energy.length + energy.curvature


def _stationarity(state):
    gradient = structural_gradient(state.points, state.points, state.pins,
                                    state.request.settings)
    scale = max(state.request.tolerances.length_scale, 1.0e-12)
    return float(np.max(np.linalg.norm(gradient, axis=1)) * scale) if len(gradient) else 0.0


def _base_candidate(state):
    settings = replace(state.request.settings, fidelity_weight=PROXIMAL_WEIGHT)
    before = perf_counter(); result = solve_structural(state.points, state.pins, settings)
    state.solve_ms += _elapsed(before); return result.points.copy()


def _contact_directions(points, closest, normals, distances, contained):
    delta = np.asarray(points) - closest; lengths = np.maximum(np.asarray(distances), 1.0e-12)
    radial = delta / lengths[:, None]; normal = _unit_rows(normals)
    use_normal = np.asarray(contained, dtype=bool) | (np.asarray(distances) <= 1.0e-12)
    return np.where(use_normal[:, None], normal, radial)


def _unit_rows(values):
    rows = np.asarray(values, dtype=np.float64); lengths = np.linalg.norm(rows, axis=1)
    fallback = np.zeros_like(rows); fallback[:, 2] = 1.0
    return np.where((lengths > 1.0e-12)[:, None], rows / np.maximum(lengths[:, None], 1.0e-12), fallback)


def _edge_samples(points, edges):
    rows, owners, factors = [], [], []
    for edge in edges:
        first, second = _edge_nodes(edge, len(points), False)
        for factor in np.linspace(0.0, 1.0, 17):
            rows.append((1.0 - factor) * np.asarray(points[first]) + factor * points[second])
            owners.append(edge); factors.append(float(factor))
    return np.asarray(rows), tuple(owners), tuple(factors)


def _closest_edge_rows(owners, distances):
    output = []
    for edge in dict.fromkeys(owners):
        rows = [index for index, owner in enumerate(owners) if owner == edge]
        output.append((rows[int(np.argmin(np.asarray(distances)[rows]))], edge))
    return tuple(output)


def _contact_rows(state, points, checked):
    edge_nodes = {index for edge in state.active_edges
                  for index in _edge_nodes(edge, len(points), _cyclic(state))}
    rows = [((index,), (1.0,), state.normals[index]) for index in state.active - edge_nodes]
    return rows + _edge_constraint_rows(state, points, checked)


def _edge_constraint_rows(state, points, checked):
    edges = tuple(sorted(state.active_edges | {int(value) for value in checked.violating_edges}))
    if not edges:
        return []
    samples, owners, factors = _edge_samples(points, edges)
    _targets, directions, distances = _contact_geometry(state, samples)
    return [_edge_constraint(points, owners[row], factors[row], directions[row])
            for row, _edge in _closest_edge_rows(owners, distances)]


def _edge_constraint(points, edge, factor, normal):
    first, second = _edge_nodes(edge, len(points), False)
    return (first, second), (1.0 - factor, factor), np.asarray(normal)


def _metric_project(state, candidate):
    rows = [row for row in state.contact_rows if _constraint_inward(row, state.points, candidate)]
    if not rows:
        return candidate
    responses = [_constraint_response(state, row) for row in rows]
    matrix = np.asarray([[_constraint_value(a, value) for value in responses] for a in rows])
    lift = 0.25 * state.request.collision_policy.collision_radius
    rhs = np.asarray([lift + _constraint_value(row, state.points - candidate) for row in rows])
    weights = np.linalg.lstsq(matrix, rhs, rcond=1.0e-10)[0]
    output = np.asarray(candidate) + sum((weight * value for weight, value in zip(weights, responses)), np.zeros_like(candidate))
    _restore_pins(output, state.pins); return output


def _constraint_inward(row, current, candidate):
    return _constraint_value(row, np.asarray(candidate) - current) < -1.0e-12


def _constraint_value(row, values):
    indices, weights, normal = row
    point = sum((weight * values[index] for index, weight in zip(indices, weights)), np.zeros(3))
    return float(np.dot(normal, point))


def _constraint_response(state, row):
    indices, weights, normal = row; rhs = np.zeros_like(state.points)
    for index, weight in zip(indices, weights):
        rhs[index] += weight * normal
    settings = replace(state.request.settings, fidelity_weight=PROXIMAL_WEIGHT)
    zeros = {index: (0.0, 0.0, 0.0) for index in state.pins}
    return solve_structural(rhs / PROXIMAL_WEIGHT, zeros, settings).points


def _accept_fractions(state, candidate, safe_step):
    for fraction in _trial_fractions(safe_step):
        proposed = _interpolate(state.points, candidate, fraction); _restore_pins(proposed, state.pins)
        checked = _timed_validation(state, proposed); accepted, full = _accept_validated(
            state, proposed, checked, fraction)
        if accepted:
            return accepted, full
    return False, False


def _trial_fractions(value):
    fraction = _backed_fraction(value)
    return tuple(fraction * (0.5 ** step) for step in range(8) if fraction * (0.5 ** step) > 1.0e-12)


def _refresh_contacts(state):
    checked = _contact_band_validation(state); prior = (set(state.active), set(state.active_edges))
    state.active = set(int(value) for value in (*checked.violating_nodes, *checked.contained_nodes))
    state.active_edges = set(int(value) for value in checked.violating_edges)
    for edge in state.active_edges:
        state.active.update(_edge_nodes(edge, len(state.points), _cyclic(state)))
    state.active_counts.append(len(state.active)); return prior != (state.active, state.active_edges), checked


def _refresh_native_contacts(state, points=None):
    prior = (set(state.active), set(state.active_edges)); started = perf_counter()
    if not state.request.colliders:
        _clear_native_contacts(state); return prior != (state.active, state.active_edges)
    edges = _chain_links(len(state.points), _cyclic(state)); values = points if points is not None else state.points
    query = _contact_query_rows(state, values, edges)
    radius = state.request.collision_policy.collision_radius; slack = state.request.tolerances.clearance_slack
    band = max(0.5 * radius, 2.0 * slack); world = _collision_world(state)
    rows = world.contacts(query[0], query[1], (("", ""),) * len(query[1]), 0.0,
                          radius + band - slack, query[3], query[4])
    _store_exact_contacts(state, edges, query[2], rows); state.contact_query_ms += _elapsed(started)
    return prior != (state.active, state.active_edges)


def _clear_native_contacts(state):
    state.active.clear(); state.active_edges.clear(); state.contact_rows.clear()
    state.active_counts.append(0)


def _collision_world(state, colliders=None):
    items = tuple(state.request.colliders if colliders is None else colliders)
    if colliders is None and state.native_world is not None:
        return state.native_world
    return cached_native_collision_world(items)


def _store_native_contacts(state, edges, rows):
    state.active_edges = {index for index, active in enumerate(rows.active) if active}
    state.active = {int(node) for edge in state.active_edges for node in edges[edge]}
    state.contact_rows = [_native_contact_row(edges[index], rows.factors[index], rows.normals[index])
                          for index in sorted(state.active_edges)]
    state.active_counts.append(len(state.active))


def _store_exact_contacts(state, edges, mapping, rows):
    selected = {}
    for index, active in enumerate(rows.active):
        if active:
            edge, low, high = mapping[index]; factor = low + (high - low) * rows.factors[index]
            if edge not in selected or rows.distances[index] < selected[edge][0]:
                selected[edge] = (rows.distances[index], factor, rows.normals[index])
    state.active_edges = set(selected); state.active = {int(node) for edge in selected for node in edges[edge]}
    state.contact_rows = [_native_contact_row(edges[edge], row[1], row[2]) for edge, row in sorted(selected.items())]
    _store_contact_normals(state, edges, selected)
    state.active_counts.append(len(state.active))


def _store_contact_normals(state, edges, selected):
    state.normals.fill(0.0)
    for edge, (_distance, factor, normal) in selected.items():
        first, second = edges[edge]; state.normals[first] += (1.0 - factor) * normal
        state.normals[second] += factor * normal
    lengths = np.linalg.norm(state.normals, axis=1)
    mask = lengths > 1.0e-12; state.normals[mask] /= lengths[mask, None]


def _contact_query_rows(state, points, edges):
    rows, mapping, only, skip = [], [], [], []
    for edge, nodes in enumerate(edges):
        contacts = _edge_contact_intervals(state.planner.contacts, edge)
        _append_query_rows(rows, mapping, only, skip, points[nodes], edge, contacts)
    values = np.asarray(rows, dtype=np.float64).reshape((-1, 2, 3))
    links = np.arange(len(rows) * 2, dtype=np.int64).reshape((-1, 2))
    return values.reshape((-1, 3)), links, tuple(mapping), tuple(only), tuple(skip)


def _edge_contact_intervals(contacts, edge):
    return tuple((item.owner_id, low, high) for item in contacts
                 for row, low, high in item.edge_intervals if row == edge)


def _append_query_rows(rows, mapping, only, skip, edge_points, edge, contacts):
    owners = tuple(dict.fromkeys(owner for owner, _low, _high in contacts))
    if len(owners) != 1:
        _append_query_row(rows, mapping, only, skip, edge_points, edge, 0.0, 1.0, "", "")
        return
    owner = owners[0]; _append_query_row(rows, mapping, only, skip, edge_points, edge, 0.0, 1.0, "", owner)
    for low, high in _remaining_intervals(contacts):
        _append_query_row(rows, mapping, only, skip, edge_points, edge, low, high, owner, "")


def _append_query_row(rows, mapping, only, skip, points, edge, low, high, include, exclude):
    delta = np.asarray(points[1]) - points[0]
    rows.append((points[0] + low * delta, points[0] + high * delta))
    mapping.append((edge, low, high)); only.append(include); skip.append(exclude)


def _remaining_intervals(contacts):
    intervals = [(0.0, 1.0)]
    for _owner, low, high in sorted(contacts, key=lambda row: row[1]):
        intervals = _remove_interval(intervals, low, high)
    return tuple(intervals)


def _remove_interval(intervals, low, high):
    rows = []
    for first, second in intervals:
        if high <= first or low >= second:
            rows.append((first, second)); continue
        if low > first: rows.append((first, min(low, second)))
        if high < second: rows.append((max(high, first), second))
    return rows


def _native_contact_row(edge, factor, normal):
    value = float(np.clip(factor, 0.0, 1.0))
    return tuple(int(index) for index in edge), (1.0 - value, value), np.asarray(normal)


def _chain_links(count, cyclic):
    first = np.arange(count if cyclic else count - 1, dtype=np.int64)
    return np.ascontiguousarray(np.column_stack((first, (first + 1) % count)))


def _edge_owner_rows(state, edges):
    owners = {}
    for contact in state.planner.contacts:
        for index in contact.node_indices:
            owners[int(index)] = contact.owner_id
    return tuple((owners.get(int(a), ""), owners.get(int(b), "")) for a, b in edges)


def _owner_span(state):
    factor = 8.0 if state.planner.mode.value == "ROADMAP" else 2.5
    return factor * state.request.collision_policy.collision_radius


def _contact_band_validation(state):
    policy, tolerance = state.request.collision_policy, state.request.tolerances
    band = max(0.5 * policy.collision_radius, 2.0 * tolerance.clearance_slack)
    return validate_static_clearance(state.points, state.snapshot, policy.collision_radius + band,
                                     state.planner.contacts, cyclic=_cyclic(state),
                                     slack=tolerance.clearance_slack)




def _normalized_step(state, proposed):
    scale = max(state.request.tolerances.length_scale, 1.0e-12)
    return float(np.max(np.linalg.norm(np.asarray(proposed) - state.points, axis=1)) / scale)


def _step_converged(state):
    return state.last_step <= state.request.tolerances.fixed_point_tolerance


def _result(request, planner, points, diagnostics, termination, validated, message,
            version=V2_SOLVER_P5_VERSION):
    backend = collision_backend_status().version
    values = tuple(tuple(float(value) for value in row) for row in points)
    return V2Result(request.signature(), termination, values, diagnostics, validated,
                    planner.mode.value, message, version, backend)


def _trace(state, started):
    planner_ms = float(state.planner.diagnostics.planner_ms + state.planner.diagnostics.handoff_ms)
    cache = state.pair_cache or V2SweepPairCache()
    return V2Package5Trace(planner_ms, state.solve_ms, state.ccd_ms, state.validation_ms,
                           state.contact_weight, state.trials, tuple(state.accepted),
                           tuple(state.fractions), tuple(state.active_counts), state.projection_scale,
                           state.candidate_ms, _elapsed(started), state.contact_query_ms,
                           state.static_validations, cache.hits, cache.misses, state.curved_waypoints)


def _failed(request, planner, started, contact_weight, optimized=False):
    version = V2_SOLVER_P51_VERSION if optimized else V2_SOLVER_P5_VERSION
    result = _result(request, planner, (), V2Diagnostics(), planner.termination, False,
                     planner.message, version)
    trace = V2Package5Trace(_elapsed(started), contact_weight=float(contact_weight))
    return V2Package5Result(result, planner, trace)


def _elapsed(started):
    return 1000.0 * (perf_counter() - started)
