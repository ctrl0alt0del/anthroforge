"""Isolated scalar-corridor Fiber V3 experiment; not imported by production."""

from collections import OrderedDict
from dataclasses import dataclass, field, replace
from hashlib import sha256
from time import perf_counter

import numpy as np

from .v2.collision import (V2SweepPairCache, build_native_collision_world_batch,
                           build_triangle_snapshot, cached_native_collision_world_batch,
                           collision_free_step, validate_static_clearance)
from .v2.contracts import V2Termination, V2Topology
from .v2 import solver_v22 as v22
from .v2 import solver_v23 as v23


V3_EXPERIMENT_VERSION = "fiber-v3-scalar-corridor-experiment-1"
V3_ALPHA_LEVELS = 33
V3_COARSE_LEVELS = 9
V3_LOCAL_LEVELS = 9
V3_DENSE_EDGE_LIMIT = 16384
_ROUTE_CACHE = OrderedDict()
_EXACT_CACHE = OrderedDict()
_CACHE_LIMIT = 128


@dataclass(frozen=True)
class V3Corridor:
    direct: tuple = ()
    roadmap: tuple = ()
    pin_indices: tuple = ()
    contacts: tuple = ()
    mode: str = ""
    signature: str = ""
    planner_ms: float = 0.0
    termination: str = V2Termination.INVALID_CONFIGURATION.value
    message: str = ""
    planner_reused: bool = False
    exact_route_hit: bool = False

    @property
    def succeeded(self):
        return self.termination == V2Termination.CONVERGED.value


@dataclass(frozen=True)
class V3Trace:
    iterations: int = 0
    accepted: int = 0
    rejected: int = 0
    contact_queries: int = 0
    ccd_queries: int = 0
    planner_ms: float = 0.0
    optimize_ms: float = 0.0
    validation_ms: float = 0.0
    seed_ms: float = 0.0
    seed_collision_ms: float = 0.0
    seed_search_ms: float = 0.0
    seed_attempts: int = 0
    seed_transitions: int = 0
    warm_start: bool = False
    exact_cache_hit: bool = False
    direction_ms: float = 0.0
    projected_residual: float = 0.0


@dataclass(frozen=True)
class V3Result:
    points: tuple = ()
    alpha: tuple = ()
    valid: bool = False
    termination: str = V2Termination.INVALID_CONFIGURATION.value
    message: str = ""
    length: float = 0.0
    curvature: float = 0.0
    objective: float = 0.0
    corridor: V3Corridor = field(default_factory=V3Corridor)
    trace: V3Trace = field(default_factory=V3Trace)


@dataclass
class _State:
    request: object
    snapshot: object
    corridor: V3Corridor
    direct: np.ndarray
    roadmap: np.ndarray
    alpha: np.ndarray
    points: np.ndarray
    edges: np.ndarray
    owners: tuple
    world: object
    pair_cache: object
    trust: float = 0.2
    accepted: int = 0
    rejected: int = 0
    iterations: int = 0
    contacts: int = 0
    ccd: int = 0
    seed_ms: float = 0.0
    seed_collision_ms: float = 0.0
    seed_search_ms: float = 0.0
    seed_attempts: int = 0
    seed_transitions: int = 0
    warm: bool = False


@dataclass(frozen=True)
class _Seed:
    alpha: np.ndarray
    warm: bool = False
    elapsed_ms: float = 0.0
    collision_ms: float = 0.0
    search_ms: float = 0.0
    attempts: int = 0
    transitions: int = 0


def plan_v3_corridor(request, snapshot=None):
    started = perf_counter(); world = _world(request)
    triangle = snapshot or build_triangle_snapshot(request.colliders)
    if request.settings.topology is not V2Topology.OPEN:
        return _failed_corridor("V3 experiment supports open Fibers only", started)
    signature = v22.v22_request_signature(request)
    planner, trace, _policy = v23._planner(request, triangle, world, signature, False, _ROUTE_CACHE)
    if not planner.succeeded:
        return _failed_corridor(planner.message or planner.termination.value, started)
    direct = _direct_reference(request, planner)
    signature = _corridor_signature(request, direct, planner.reference, planner.pin_indices)
    return V3Corridor(_tuples(direct), tuple(planner.reference), tuple(planner.pin_indices),
                      tuple(planner.contacts), planner.mode.value, signature, _ms(started),
                      V2Termination.CONVERGED.value, "paired corridor ready", trace[0], trace[1])


def solve_v3_corridor(request, snapshot=None, warm_points=(), warm_signature="", allow_exact_cache=True):
    started = perf_counter(); triangle = snapshot or build_triangle_snapshot(request.colliders)
    corridor = plan_v3_corridor(request, triangle)
    if not corridor.succeeded:
        return _failed_result(corridor)
    cached = _exact_result(request, triangle, corridor) if allow_exact_cache else None
    if cached is not None: return cached
    state = _state(request, triangle, corridor, warm_points, warm_signature)
    termination, message = _iterate(state)
    result = _finish(state, termination, message, started)
    if result.valid: _cache_exact(result)
    return result


def _exact_result(request, snapshot, corridor):
    result = _EXACT_CACHE.get(corridor.signature)
    if result is None: return None
    started = perf_counter(); valid = _exact_valid(request, snapshot, corridor, result.points)
    if not valid: _EXACT_CACHE.pop(corridor.signature, None); return None
    _EXACT_CACHE.move_to_end(corridor.signature)
    trace = V3Trace(planner_ms=corridor.planner_ms, validation_ms=_ms(started),
                    warm_start=True, exact_cache_hit=True)
    return replace(result, corridor=corridor, trace=trace, message="exact validated V3 cache hit")


def _cache_exact(result):
    _EXACT_CACHE[result.corridor.signature] = result
    _EXACT_CACHE.move_to_end(result.corridor.signature)
    while len(_EXACT_CACHE) > _CACHE_LIMIT: _EXACT_CACHE.popitem(last=False)


def _failed_corridor(message, started):
    return V3Corridor(planner_ms=_ms(started), message=str(message))


def _failed_result(corridor):
    return V3Result(termination=corridor.termination, message=corridor.message, corridor=corridor,
                    trace=V3Trace(planner_ms=corridor.planner_ms))


def _direct_reference(request, planner):
    points = np.empty((request.settings.node_count, 3), dtype=np.float64)
    for left, right, a, b in _pin_spans(planner.pin_indices, request.anchors):
        points[left:right + 1] = np.linspace(a.point, b.point, right - left + 1)
    return points


def _pin_spans(indices, anchors):
    return tuple((int(a), int(b), first, second) for a, b, first, second in
                 zip(indices[:-1], indices[1:], anchors[:-1], anchors[1:]))


def _corridor_signature(request, direct, roadmap, pins):
    digest = sha256(); digest.update(np.asarray(direct).tobytes()); digest.update(np.asarray(roadmap).tobytes())
    digest.update(np.asarray(pins, dtype=np.int64).tobytes())
    digest.update(str((request.source_revision, request.settings, request.collision_policy)).encode())
    return digest.hexdigest()


def _state(request, snapshot, corridor, warm_points, warm_signature):
    direct, roadmap = np.asarray(corridor.direct), np.asarray(corridor.roadmap)
    edges = _edges(len(direct)); world = _world(request)
    owners = _edge_owners(corridor.contacts, edges)
    seed = _initial_alpha(request, snapshot, corridor, direct, roadmap,
                          warm_points, warm_signature, world, edges, owners)
    points = _corridor_points(direct, roadmap, seed.alpha)
    return _State(request, snapshot, corridor, direct, roadmap, seed.alpha, points, edges,
                  owners, world, V2SweepPairCache(), seed_ms=seed.elapsed_ms,
                  seed_collision_ms=seed.collision_ms, seed_search_ms=seed.search_ms,
                  seed_attempts=seed.attempts, seed_transitions=seed.transitions, warm=seed.warm)


def _initial_alpha(request, snapshot, corridor, direct, roadmap, warm, signature, world, edges, owners):
    started = perf_counter()
    if not warm or signature != corridor.signature:
        return _layered_alpha(request, snapshot, corridor, direct, roadmap, world, edges, started)
    alpha = _project_alpha(np.asarray(warm), direct, roadmap)
    points = _corridor_points(direct, roadmap, alpha)
    if _exact_valid(request, snapshot, corridor, points):
        return _Seed(alpha, True, _ms(started))
    return _layered_alpha(request, snapshot, corridor, direct, roadmap, world, edges, started)


def _layered_alpha(request, snapshot, corridor, direct, roadmap, world, chain, started):
    count = _level_count(len(direct)); levels = np.linspace(0.0, 1.0, count)
    alpha, stats = _solve_level_grid(request, snapshot, corridor, direct, roadmap, world, levels)
    if count < V3_ALPHA_LEVELS:
        local = _local_levels(alpha, 1.0 / max(1, count - 1))
        alpha, extra = _solve_level_grid(request, snapshot, corridor, direct, roadmap, world, local)
        stats = tuple(a + b for a, b in zip(stats, extra))
    return _Seed(alpha, False, _ms(started), stats[0], stats[1], int(stats[2]), int(stats[3]))


def _solve_level_grid(request, snapshot, corridor, direct, roadmap, world, levels):
    samples = _level_samples(direct, roadmap, levels); collision_started = perf_counter()
    clear = _layer_clear(world, samples, corridor.contacts, _request_threshold(request))
    collision_ms = _ms(collision_started); search_started = perf_counter()
    alpha, attempts = _lazy_layered_alpha(request, snapshot, corridor, samples, levels, clear)
    transitions = (len(samples) - 1) * len(samples[0]) ** 2
    return alpha, (collision_ms, _ms(search_started), attempts, transitions)


def _level_samples(direct, roadmap, levels):
    values = np.asarray(levels, dtype=np.float64)
    if values.ndim == 1: values = np.broadcast_to(values, (len(direct), len(values)))
    return direct[:, None, :] + values[:, :, None] * (roadmap - direct)[:, None, :]


def _local_levels(alpha, radius):
    offsets = np.linspace(-radius, radius, V3_LOCAL_LEVELS)
    return np.clip(np.asarray(alpha)[:, None] + offsets[None, :], 0.0, 1.0)


def _lazy_layered_alpha(request, snapshot, corridor, samples, levels, clear):
    for attempt in range(128):
        indices = _corridor_dp(request, samples, clear); alpha = _selected_levels(levels, indices)
        points = samples[np.arange(len(samples)), indices]
        result = _exact_clearance(request, snapshot, corridor, points)
        if result.valid: return alpha, attempt + 1
        if not _exclude_route(clear, indices, result): break
    return np.ones(len(samples), dtype=np.float64), attempt + 1


def _selected_levels(levels, indices):
    values = np.asarray(levels)
    return values[indices] if values.ndim == 1 else values[np.arange(len(indices)), indices]


def _layer_clear(world, samples, contacts, threshold):
    points, links, mapping, only, skip = _layer_queries(samples, contacts)
    owners = (("", ""),) * len(links)
    rows = world.contacts(points, links, owners, 0.0, threshold, only, skip)
    clear = np.ones((len(samples) - 1) * len(samples[0]) ** 2, dtype=bool)
    for query, active in enumerate(rows.active):
        if active: clear[mapping[query]] = False
    return clear.reshape((len(samples) - 1, len(samples[0]), len(samples[0])))


def _layer_queries(samples, contacts):
    rows, mapping, only, skip = [], [], [], []
    levels = len(samples[0])
    for layer in range(len(samples) - 1):
        segments = _layer_segments(samples, layer)
        _append_layer_queries(rows, mapping, only, skip, segments, layer, levels, contacts)
    values = np.asarray(rows, dtype=np.float64).reshape((-1, 2, 3))
    links = np.arange(len(rows) * 2, dtype=np.int64).reshape((-1, 2))
    return values.reshape((-1, 3)), links, np.asarray(mapping), tuple(only), tuple(skip)


def _layer_segments(samples, layer):
    count = len(samples[0]); first = np.broadcast_to(samples[layer][:, None, :], (count, count, 3))
    second = np.broadcast_to(samples[layer + 1][None, :, :], (count, count, 3))
    return np.stack((first, second), axis=2).reshape((-1, 2, 3))


def _append_layer_queries(rows, mapping, only, skip, segments, edge, levels, contacts):
    intervals = _edge_contact_intervals(contacts, edge)
    owners = tuple(dict.fromkeys(row[0] for row in intervals))
    if len(owners) != 1:
        _append_segment_rows(rows, mapping, only, skip, segments, edge * levels ** 2, "", "")
        return
    owner = owners[0]; base = edge * levels ** 2
    _append_segment_rows(rows, mapping, only, skip, segments, base, "", owner)
    for low, high in _remaining_intervals(intervals):
        _append_segment_rows(rows, mapping, only, skip, _subsegments(segments, low, high), base, owner, "")


def _append_segment_rows(rows, mapping, only, skip, segments, base, include, exclude):
    rows.extend(segments); mapping.extend(range(base, base + len(segments)))
    only.extend((include,) * len(segments)); skip.extend((exclude,) * len(segments))


def _edge_contact_intervals(contacts, edge):
    return tuple((item.owner_id, low, high) for item in contacts
                 for row, low, high in item.edge_intervals if row == edge)


def _remaining_intervals(contacts):
    intervals = [(0.0, 1.0)]
    for _owner, low, high in sorted(contacts, key=lambda row: row[1]):
        intervals = _subtract_intervals(intervals, low, high)
    return tuple(intervals)


def _subtract_intervals(intervals, start, end):
    output = []
    for low, high in intervals:
        if end <= low or start >= high: output.append((low, high)); continue
        if start > low: output.append((low, min(start, high)))
        if end < high: output.append((max(end, low), high))
    return output


def _subsegments(segments, low, high):
    delta = segments[:, 1] - segments[:, 0]
    return np.stack((segments[:, 0] + low * delta, segments[:, 0] + high * delta), axis=1)


def _exclude_route(clear, indices, result):
    changed = False
    for edge in result.violating_edges:
        clear[int(edge), indices[int(edge)], indices[int(edge) + 1]] = False; changed = True
    for node in (*result.violating_nodes, *result.contained_nodes):
        changed |= _exclude_node(clear, indices, int(node))
    return changed


def _exclude_node(clear, indices, node):
    changed = False; level = indices[node]
    if node > 0: clear[node - 1, :, level] = False; changed = True
    if node < len(indices) - 1: clear[node, level, :] = False; changed = True
    return changed


def _corridor_dp(request, samples, clear):
    edge_costs = _edge_costs(request, samples, clear); prior = edge_costs[0]
    back = []
    for layer in range(1, len(edge_costs)):
        total = prior[:, :, None] + edge_costs[layer][None, :, :] + _bend_costs(request, samples, layer)
        choice = np.argmin(total, axis=0); prior = np.min(total, axis=0); back.append(choice)
    return _backtrack_levels(prior, back, len(samples))


def _edge_costs(request, samples, clear):
    rows = []
    for layer in range(len(samples) - 1):
        delta = samples[layer][:, None, :] - samples[layer + 1][None, :, :]
        cost = request.settings.length_weight * np.linalg.norm(delta, axis=2)
        rows.append(np.where(clear[layer], cost, np.inf))
    return tuple(rows)


def _bend_costs(request, samples, layer):
    previous = samples[layer - 1][:, None, None, :]
    current = samples[layer][None, :, None, :]; following = samples[layer + 1][None, None, :, :]
    second = previous - 2.0 * current + following
    factor = _curvature_factor(request, len(samples))
    return request.settings.curvature_weight * factor * np.einsum("abci,abci->abc", second, second)


def _backtrack_levels(cost, back, count):
    last = np.unravel_index(int(np.argmin(cost)), cost.shape); output = [0] * count
    output[-2], output[-1] = map(int, last)
    for layer in range(count - 3, -1, -1):
        output[layer] = int(back[layer][output[layer + 1], output[layer + 2]])
    return np.asarray(output, dtype=np.int64)


def _project_alpha(points, direct, roadmap):
    if points.shape != direct.shape:
        return np.ones(len(direct), dtype=np.float64)
    vectors = roadmap - direct; scale = np.einsum("ij,ij->i", vectors, vectors)
    numer = np.einsum("ij,ij->i", points - direct, vectors)
    return np.clip(np.divide(numer, scale, out=np.ones_like(numer), where=scale > 1.0e-18), 0.0, 1.0)


def _iterate(state):
    prior = _objective(state, state.points)
    for index in range(max(1, state.request.settings.max_accepted_steps)):
        state.iterations = index + 1; direction = _direction(state)
        accepted, value = _trial(state, direction, prior)
        if accepted:
            if _converged(state, prior, value): return V2Termination.CONVERGED.value, "scalar corridor converged"
            prior = value; state.trust = min(0.35, state.trust * 1.15)
        else:
            state.rejected += 1
            return V2Termination.STALLED.value, "complete scalar line search found no improving step"
    return V2Termination.BUDGET_EXHAUSTED.value, "accepted-step cap exhausted"


def _direction(state):
    gradient = _point_gradient(state, state.points); vectors = state.roadmap - state.direct
    diagonal = np.maximum(np.einsum("ij,ij->i", vectors, vectors), 1.0e-12)
    direction = -np.einsum("ij,ij->i", gradient, vectors) / diagonal
    direction = _smooth_direction(direction, state.corridor.pin_indices)
    direction = _project_contacts(state, direction, vectors)
    maximum = float(np.max(np.abs(direction))) if len(direction) else 0.0
    return direction if maximum <= state.trust else direction * (state.trust / maximum)


def _smooth_direction(direction, pins):
    output = np.asarray(direction).copy(); pinned = set(int(value) for value in pins)
    for _pass in range(2):
        prior = output.copy(); output[1:-1] = 0.25 * prior[:-2] + 0.5 * prior[1:-1] + 0.25 * prior[2:]
        for index in pinned: output[index] = 0.0
    return output


def _project_contacts(state, direction, vectors):
    threshold = _threshold(state); band = max(0.5 * state.request.collision_policy.collision_radius,
                                              2.0 * state.request.tolerances.clearance_slack)
    rows, mapping = _chain_contacts(state, state.points, threshold + band); state.contacts += 1
    output = np.asarray(direction).copy()
    for _pass in range(3):
        for query, active in enumerate(rows.active):
            if active: _project_mapped_contact(output, vectors, state.edges, rows, mapping, query)
    return output


def _project_mapped_contact(direction, vectors, edges, rows, mapping, query):
    edge, low, high = mapping[query]
    factor = low + (high - low) * rows.factors[query]
    _project_contact_row(direction, vectors, edges[edge], factor, rows.normals[query])


def _project_contact_row(direction, vectors, edge, factor, normal):
    first, second = map(int, edge); weights = (1.0 - float(factor), float(factor))
    coefficients = np.asarray([weights[0] * np.dot(normal, vectors[first]),
                               weights[1] * np.dot(normal, vectors[second])])
    inward = float(coefficients[0] * direction[first] + coefficients[1] * direction[second])
    scale = float(np.dot(coefficients, coefficients))
    if inward < 0.0 and scale > 1.0e-18:
        direction[first] -= inward * coefficients[0] / scale
        direction[second] -= inward * coefficients[1] / scale


def _trial(state, direction, prior):
    target_alpha = np.clip(state.alpha + direction, 0.0, 1.0)
    target = _corridor_points(state.direct, state.roadmap, target_alpha)
    candidate, alpha = _ccd_candidate(state, target, target_alpha)
    for depth in range(8):
        fraction = 0.5 ** depth
        trial = state.points + fraction * (candidate - state.points)
        trial_alpha = state.alpha + fraction * (alpha - state.alpha); value = _objective(state, trial)
        if value < prior - 1.0e-10 * max(1.0, prior):
            state.alpha, state.points = trial_alpha, trial; state.accepted += 1; return True, value
    return False, prior


def _ccd_candidate(state, candidate, alpha):
    step = collision_free_step(state.points, candidate, state.snapshot,
                               state.request.collision_policy.collision_radius,
                               state.corridor.contacts, slack=state.request.tolerances.clearance_slack,
                               pair_cache=state.pair_cache, assume_initial_valid=True)
    state.ccd += 1
    if not step.valid or step.safe_step <= 1.0e-10:
        return state.points, state.alpha
    fraction = 1.0 if step.safe_step >= 1.0 else 0.999 * step.safe_step
    return (state.points + fraction * (candidate - state.points),
            state.alpha + fraction * (alpha - state.alpha))


def _chain_contacts(state, points, threshold):
    values, links, mapping, only, skip = _chain_queries(points, state.edges, state.corridor.contacts)
    owners = (("", ""),) * len(links)
    return state.world.contacts(values, links, owners, 0.0, threshold, only, skip), mapping


def _chain_queries(points, edges, contacts):
    rows, mapping, only, skip = [], [], [], []
    for edge, nodes in enumerate(edges):
        _append_contact_queries(rows, mapping, only, skip, np.asarray(points)[nodes], edge, contacts)
    values = np.asarray(rows, dtype=np.float64).reshape((-1, 2, 3))
    links = np.arange(len(rows) * 2, dtype=np.int64).reshape((-1, 2))
    return values.reshape((-1, 3)), links, tuple(mapping), tuple(only), tuple(skip)


def _append_contact_queries(rows, mapping, only, skip, segment, edge, contacts):
    intervals = _edge_contact_intervals(contacts, edge)
    owners = tuple(dict.fromkeys(row[0] for row in intervals))
    if len(owners) != 1:
        _append_contact_row(rows, mapping, only, skip, segment, edge, 0.0, 1.0, "", ""); return
    owner = owners[0]
    _append_contact_row(rows, mapping, only, skip, segment, edge, 0.0, 1.0, "", owner)
    for low, high in _remaining_intervals(intervals):
        _append_contact_row(rows, mapping, only, skip, segment, edge, low, high, owner, "")


def _append_contact_row(rows, mapping, only, skip, segment, edge, low, high, include, exclude):
    delta = segment[1] - segment[0]
    rows.append((segment[0] + low * delta, segment[0] + high * delta))
    mapping.append((edge, low, high)); only.append(include); skip.append(exclude)


def _exact_valid(request, snapshot, corridor, points):
    return bool(_exact_clearance(request, snapshot, corridor, points).valid)


def _exact_clearance(request, snapshot, corridor, points):
    return validate_static_clearance(points, snapshot, request.collision_policy.collision_radius,
                                     corridor.contacts, slack=request.tolerances.clearance_slack)


def _finish(state, termination, message, started):
    validation = perf_counter(); valid = _exact_valid(state.request, state.snapshot,
                                                       state.corridor, state.points)
    validation_ms = _ms(validation); length, curvature, objective = _metrics(state, state.points)
    reason = termination if valid else V2Termination.UNSAFE_OUTPUT.value
    text = message if valid else "independent final validation failed"
    trace = V3Trace(state.iterations, state.accepted, state.rejected, state.contacts, state.ccd,
                    state.corridor.planner_ms, _ms(started) - validation_ms,
                    validation_ms, state.seed_ms, state.seed_collision_ms, state.seed_search_ms,
                    state.seed_attempts,
                    state.seed_transitions, state.warm)
    return V3Result(_tuples(state.points), tuple(map(float, state.alpha)), valid, reason, text,
                    length, curvature, objective, state.corridor, trace)


def _metrics(state, points):
    edges = np.diff(points, axis=0); length = float(np.linalg.norm(edges, axis=1).sum())
    second = points[:-2] - 2.0 * points[1:-1] + points[2:]
    curvature = float(np.einsum("ij,ij->", second, second))
    factor = _curvature_factor(state.request, len(points))
    objective = state.request.settings.length_weight * length + state.request.settings.curvature_weight * factor * curvature
    return length, curvature, float(objective)


def _objective(state, points):
    return _metrics(state, points)[2]


def _point_gradient(state, points):
    gradient = np.zeros_like(points); edges = np.diff(points, axis=0)
    unit = edges / np.maximum(np.linalg.norm(edges, axis=1), 1.0e-12)[:, None]
    gradient[:-1] -= state.request.settings.length_weight * unit
    gradient[1:] += state.request.settings.length_weight * unit
    return gradient + _curvature_gradient(state, points)


def _curvature_gradient(state, points):
    second = points[:-2] - 2.0 * points[1:-1] + points[2:]
    factor = 2.0 * state.request.settings.curvature_weight * _curvature_factor(state.request, len(points))
    result = np.zeros_like(points)
    result[:-2] += factor * second; result[1:-1] -= 2.0 * factor * second; result[2:] += factor * second
    return result


def _converged(state, before, after):
    relative = abs(before - after) / max(1.0, abs(before))
    return relative < state.request.tolerances.relative_energy_tolerance and state.trust < 0.02


def _edge_owners(contacts, edges):
    owners = {}
    for contact in contacts:
        for index in contact.node_indices: owners[int(index)] = contact.owner_id
    return tuple((owners.get(int(a), ""), owners.get(int(b), "")) for a, b in edges)


def _owner_span(state):
    return _corridor_owner_span(state.request, state.corridor)


def _corridor_owner_span(request, corridor):
    factor = 8.0 if corridor.mode == "ROADMAP" else 2.5
    return factor * request.collision_policy.collision_radius


def _threshold(state):
    return _request_threshold(state.request)


def _request_threshold(request):
    return max(0.0, request.collision_policy.collision_radius -
               request.tolerances.clearance_slack)


def _level_count(nodes):
    dense = max(0, int(nodes) - 1) * V3_ALPHA_LEVELS ** 2
    return V3_COARSE_LEVELS if dense > V3_DENSE_EDGE_LIMIT else V3_ALPHA_LEVELS


def _world(request):
    key = v22.v22_snapshot_key(request)
    return (cached_native_collision_world_batch(request.colliders, key) if key else
            build_native_collision_world_batch(request.colliders))


def clear_v3_experiment_caches():
    _ROUTE_CACHE.clear(); _EXACT_CACHE.clear()


def _corridor_points(direct, roadmap, alpha):
    return direct + np.asarray(alpha)[:, None] * (roadmap - direct)


def _edges(count):
    first = np.arange(count - 1, dtype=np.int64)
    return np.ascontiguousarray(np.column_stack((first, first + 1)))


def _path_length(points):
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def _curvature_factor(request, count):
    scale = max(request.tolerances.length_scale, 1.0e-9)
    return float(max(1, count - 1) ** 3) / scale


def _tuples(points):
    return tuple(tuple(map(float, row)) for row in np.asarray(points))


def _ms(started):
    return 1000.0 * (perf_counter() - started)
