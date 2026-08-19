"""Isolated transverse-corridor V3 experiment; not imported by production."""

from dataclasses import dataclass, field
from time import perf_counter

import numpy as np

from .v2.collision import V2SweepPairCache, build_triangle_snapshot
from .v2.contracts import V2Termination
from . import v3_experiment as base


V3_TRANSVERSE_VERSION = "fiber-v3-transverse-corridor-experiment-1"
BOUND_SAMPLES = 17
MIDPOINT_WEIGHT = 50.0
MIDPOINT_SMOOTH_PASSES = 8
WINDOW_RADIUS = 5


@dataclass(frozen=True)
class V3TransverseTrace:
    interval_ms: float = 0.0
    seed_ms: float = 0.0
    optimize_ms: float = 0.0
    validation_ms: float = 0.0
    interval_queries: int = 0
    seed_transitions: int = 0
    seed_attempts: int = 0
    iterations: int = 0
    accepted_steps: int = 0
    rejected_steps: int = 0
    contact_queries: int = 0
    ccd_queries: int = 0
    active_nodes: int = 0


@dataclass(frozen=True)
class V3TransverseResult:
    points: tuple = ()
    candidate_points: tuple = ()
    lower: tuple = ()
    middle: tuple = ()
    upper: tuple = ()
    beta: tuple = ()
    valid: bool = False
    accepted: bool = False
    mode: str = ""
    termination: str = V2Termination.INVALID_CONFIGURATION.value
    message: str = ""
    length: float = 0.0
    free_max_turn: float = 0.0
    free_p95_turn: float = 0.0
    trace: V3TransverseTrace = field(default_factory=V3TransverseTrace)
    first_pass: object = None


def solve_v3_transverse(request, snapshot=None, first_pass=None, mode="windowed"):
    triangle = snapshot or build_triangle_snapshot(request.colliders)
    prior = first_pass or base.solve_v3_corridor(request, triangle)
    if not prior.valid: return _failed(prior, mode, "first V3 pass is not valid")
    started = perf_counter(); frame = _frame(prior)
    active = _active_mask(prior.points, prior.corridor.pin_indices, mode)
    bounds, interval_stats = _bounds(request, prior, frame, active)
    candidate, state, seed_stats, phase_ms = _second_pass(request, triangle, prior, bounds)
    return _finish(request, triangle, prior, bounds, candidate, state, mode,
                   active, interval_stats, seed_stats, phase_ms, started)


def _frame(result):
    points = np.asarray(result.points); tangents = _tangents(points)
    ribbon = np.asarray(result.corridor.roadmap) - np.asarray(result.corridor.direct)
    raw = np.cross(tangents, ribbon); valid = np.linalg.norm(raw, axis=1) > 1.0e-10
    return _fill_axes(tangents, raw, valid)


def _tangents(points):
    values = np.empty_like(points); values[0] = points[1] - points[0]
    values[-1] = points[-1] - points[-2]; values[1:-1] = points[2:] - points[:-2]
    return _normalized(values)


def _fill_axes(tangents, raw, valid):
    axes = np.zeros_like(raw); seed = int(np.flatnonzero(valid)[0]) if np.any(valid) else 0
    axes[seed] = _unit(raw[seed], _fallback_axis(tangents[seed]))
    for index in range(seed + 1, len(axes)):
        axes[index] = _next_axis(axes[index - 1], tangents[index - 1], tangents[index], raw[index], valid[index])
    for index in range(seed - 1, -1, -1):
        axes[index] = _next_axis(axes[index + 1], tangents[index + 1], tangents[index], raw[index], valid[index])
    return axes


def _next_axis(previous, old_tangent, tangent, raw, valid):
    carried = _transport(previous, old_tangent, tangent)
    if not valid: return carried
    aligned = raw if np.dot(raw, carried) >= 0.0 else -raw
    return _unit(aligned, carried)


def _transport(axis, first, second):
    cross = np.cross(first, second); sine = float(np.linalg.norm(cross)); cosine = float(np.dot(first, second))
    if sine < 1.0e-10: return _unit(axis - np.dot(axis, second) * second, _fallback_axis(second))
    direction = cross / sine
    rotated = axis * cosine + np.cross(direction, axis) * sine + direction * np.dot(direction, axis) * (1.0 - cosine)
    return _unit(rotated - np.dot(rotated, second) * second, _fallback_axis(second))


def _fallback_axis(tangent):
    basis = np.eye(3)[int(np.argmin(np.abs(tangent)))]
    return _unit(np.cross(tangent, basis), np.asarray((0.0, 1.0, 0.0)))


def _normalized(values):
    lengths = np.linalg.norm(values, axis=1)
    return values / np.maximum(lengths, 1.0e-12)[:, None]


def _unit(value, fallback):
    length = float(np.linalg.norm(value))
    return np.asarray(value) / length if length > 1.0e-12 else np.asarray(fallback)


def _active_mask(points, pins, mode):
    active = np.ones(len(points), dtype=bool)
    if mode == "windowed": active = _turn_windows(points, pins)
    active[np.asarray(pins, dtype=np.int64)] = False
    return active


def _turn_windows(points, pins):
    turns = _turn_values(points); free = np.ones(len(points), dtype=bool)
    free[np.asarray(pins, dtype=np.int64)] = False; available = turns[free]
    threshold = max(12.0, float(np.percentile(available, 85))) if len(available) else 180.0
    selected = np.flatnonzero((turns >= threshold) & free)
    if not len(selected) and np.any(free): selected = np.asarray([int(np.argmax(np.where(free, turns, -1.0)))])
    return _expanded_mask(len(points), selected)


def _expanded_mask(count, selected):
    output = np.zeros(count, dtype=bool)
    for index in selected:
        low, high = max(0, int(index) - WINDOW_RADIUS), min(count, int(index) + WINDOW_RADIUS + 1)
        output[low:high] = True
    return output


def _turn_values(points):
    values = np.asarray(points); first, second = np.diff(values, axis=0)[:-1], np.diff(values, axis=0)[1:]
    scale = np.linalg.norm(first, axis=1) * np.linalg.norm(second, axis=1)
    angles = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", first, second) / np.maximum(scale, 1e-12), -1, 1)))
    return np.pad(angles, (1, 1))


def _bounds(request, result, axes, active):
    started = perf_counter(); points = np.asarray(result.points)
    caps = _caps(request, result, active); rows, keys = _bound_rows(points, axes, caps, active)
    clear = _bound_clear(request, result, rows); low, high = _bound_values(caps, active, clear, keys)
    return (low, high, axes), (_ms(started), len(rows))


def _caps(request, result, active):
    points = np.asarray(result.points); edges = np.linalg.norm(np.diff(points, axis=0), axis=1)
    spacing = np.r_[edges[0], 0.5 * (edges[:-1] + edges[1:]), edges[-1]]
    ribbon = np.linalg.norm(np.asarray(result.corridor.roadmap) - np.asarray(result.corridor.direct), axis=1)
    raw = np.maximum.reduce((2.0 * spacing, 0.2 * ribbon,
                             np.full(len(points), 8.0 * request.collision_policy.collision_radius)))
    return np.where(active, np.minimum(raw, 0.08 * request.tolerances.length_scale), 0.0)


def _bound_rows(points, axes, caps, active):
    rows, keys = [], []
    for node in np.flatnonzero(active):
        for sign in (-1.0, 1.0):
            for step in range(1, BOUND_SAMPLES + 1):
                candidate = points[node] + sign * step * caps[node] * axes[node] / BOUND_SAMPLES
                rows.append((candidate, candidate))
                keys.append((int(node), int(sign), step))
    return np.asarray(rows, dtype=np.float64), tuple(keys)


def _bound_clear(request, result, rows):
    if not len(rows): return ()
    values = rows.reshape((-1, 3)); links = np.arange(len(values), dtype=np.int64).reshape((-1, 2))
    owners = (("", ""),) * len(links); threshold = base._request_threshold(request)
    return tuple(not value for value in base._world(request).contacts(
        values, links, owners, 0.0, threshold).active)


def _bound_values(caps, active, clear, keys):
    low = np.zeros(len(caps)); high = np.zeros(len(caps)); blocked = set()
    for safe, (node, sign, step) in zip(clear, keys):
        key = (node, sign)
        if key in blocked: continue
        if not safe: blocked.add(key); continue
        value = sign * step * caps[node] / BOUND_SAMPLES
        if sign < 0: low[node] = value
        else: high[node] = value
    return low, high


def _second_pass(request, snapshot, result, bounds):
    started = perf_counter(); lower, upper, gamma, stats = _transverse_seed(request, snapshot, result, bounds)
    seed_ms = _ms(started); state, termination, message = _refine(request, snapshot, result, lower, upper, gamma)
    return state.points, state, (seed_ms, *stats), (termination, message)


def _transverse_seed(request, snapshot, result, bounds):
    low, high, axes = bounds; points = np.asarray(result.points)
    lower = points + low[:, None] * axes; upper = points + high[:, None] * axes
    current = np.divide(-low, high - low, out=np.zeros_like(low), where=(high - low) > 1.0e-12)
    target = _target_gamma(low, high); levels = _initial_levels(current, target)
    gamma, stats = _grid(request, snapshot, result, lower, upper, levels, current, target)
    local = base._local_levels(gamma, 1.0 / (base.V3_COARSE_LEVELS - 1))
    gamma, extra = _grid(request, snapshot, result, lower, upper, local, current, target)
    return lower, upper, gamma, tuple(a + b for a, b in zip(stats, extra))


def _target_gamma(low, high):
    beta = _smooth_middle(low, high); width = high - low
    return np.divide(beta - low, width, out=np.zeros_like(low), where=width > 1.0e-12)


def _smooth_middle(low, high):
    beta = 0.5 * (low + high)
    for _pass in range(MIDPOINT_SMOOTH_PASSES):
        prior = beta.copy(); beta[1:-1] = 0.25 * prior[:-2] + 0.5 * prior[1:-1] + 0.25 * prior[2:]
        beta = np.clip(beta, low, high)
    return beta


def _initial_levels(current, target):
    rows = np.broadcast_to(np.linspace(0.0, 1.0, base.V3_COARSE_LEVELS), (len(current), base.V3_COARSE_LEVELS)).copy()
    for index, values in enumerate(zip(current, target)): rows[index] = _insert_levels(rows[index], values)
    return np.sort(rows, axis=1)


def _insert_levels(row, values):
    output = row.copy(); used = set()
    for value in values:
        choices = np.argsort(np.abs(output - value))
        slot = next((int(index) for index in choices if int(index) not in used), int(choices[0]))
        output[slot] = value; used.add(slot)
    return output


def _grid(request, snapshot, result, lower, upper, levels, fallback, target):
    samples = base._level_samples(lower, upper, levels); collision = perf_counter()
    clear = base._layer_clear(base._world(request), samples, result.corridor.contacts, base._request_threshold(request))
    collision_ms = _ms(collision); search = perf_counter()
    gamma, attempts = _lazy_grid(request, snapshot, result, samples, levels, clear, fallback, target)
    transitions = (len(samples) - 1) * len(samples[0]) ** 2
    return gamma, (collision_ms, _ms(search), attempts, transitions)


def _lazy_grid(request, snapshot, result, samples, levels, clear, fallback, target):
    for attempt in range(32):
        indices = _transverse_dp(request, samples, clear, target); gamma = base._selected_levels(levels, indices)
        points = samples[np.arange(len(samples)), indices]
        checked = base._exact_clearance(request, snapshot, result.corridor, points)
        if checked.valid: return gamma, attempt + 1
        if not base._exclude_route(clear, indices, checked): break
    return np.asarray(fallback), attempt + 1


def _transverse_dp(request, samples, clear, target):
    costs = _transverse_edges(request, samples, clear, target); prior = costs[0]; back = []
    for layer in range(1, len(costs)):
        total = prior[:, :, None] + costs[layer][None, :, :] + base._bend_costs(request, samples, layer)
        choice = np.argmin(total, axis=0); prior = np.min(total, axis=0); back.append(choice)
    return base._backtrack_levels(prior, back, len(samples))


def _transverse_edges(request, samples, clear, target):
    structural = base._edge_costs(request, samples, clear); midpoint = _midpoint_costs(request, samples, target)
    return tuple(row + 0.5 * (midpoint[index][:, None] + midpoint[index + 1][None, :])
                 for index, row in enumerate(structural))


def _midpoint_costs(request, samples, target):
    levels = _sample_parameters(samples); normalized = levels - np.asarray(target)[:, None]
    edge = request.tolerances.length_scale / max(1, len(samples) - 1)
    return MIDPOINT_WEIGHT * request.settings.length_weight * edge * normalized ** 2


def _sample_parameters(samples):
    direction = samples[:, -1] - samples[:, 0]; scale = np.einsum("ij,ij->i", direction, direction)
    offset = samples - samples[:, :1]
    return np.divide(np.einsum("ijk,ik->ij", offset, direction), scale[:, None],
                     out=np.zeros(offset.shape[:2]), where=scale[:, None] > 1.0e-18)


def _refine(request, snapshot, result, lower, upper, gamma):
    points = base._corridor_points(lower, upper, gamma); edges = base._edges(len(points))
    state = base._State(request, snapshot, result.corridor, lower, upper, gamma, points, edges,
                        base._edge_owners(result.corridor.contacts, edges), base._world(request), V2SweepPairCache())
    termination, message = base._iterate(state)
    return state, termination, message


def _finish(request, snapshot, prior, bounds, candidate, state, mode, active, interval, seed, phase, started):
    validation = perf_counter(); valid = base._exact_valid(request, snapshot, prior.corridor, candidate)
    validation_ms = _ms(validation); accepted = valid and _better(prior, candidate)
    points = candidate if accepted else np.asarray(prior.points); turns = _free_turns(points, prior.corridor.pin_indices)
    trace = _trace(interval, seed, state, active, validation_ms, _ms(started))
    reason = phase[0] if valid else V2Termination.UNSAFE_OUTPUT.value
    message = phase[1] if accepted else _rejection_message(valid)
    return _result(points, candidate, bounds, prior, state.alpha, valid, accepted, mode,
                   reason, message, turns, trace)


def _trace(interval, seed, state, active, validation_ms, total_ms):
    seed_ms, collision_ms, search_ms, attempts, transitions = seed
    optimize_ms = max(0.0, total_ms - interval[0] - seed_ms - validation_ms)
    return V3TransverseTrace(interval[0], seed_ms, optimize_ms, validation_ms, interval[1],
                             int(transitions), int(attempts), state.iterations, state.accepted,
                             state.rejected, state.contacts, state.ccd, int(np.count_nonzero(active)))


def _result(points, candidate, bounds, prior, gamma, valid, accepted, mode, reason, message, turns, trace):
    low, high, axes = bounds; center = np.asarray(prior.points)
    lower = center + low[:, None] * axes; upper = center + high[:, None] * axes
    middle = center + _smooth_middle(low, high)[:, None] * axes
    beta = low + np.asarray(gamma) * (high - low)
    return V3TransverseResult(base._tuples(points), base._tuples(candidate), base._tuples(lower),
                              base._tuples(middle), base._tuples(upper), tuple(map(float, beta)),
                              valid, accepted, mode, reason, message, base._path_length(points),
                              turns[0], turns[1], trace, prior)


def _free_turns(points, pins):
    turns = _turn_values(points); mask = np.ones(len(turns), dtype=bool)
    mask[np.asarray(pins, dtype=np.int64)] = False; values = turns[mask]
    return (float(np.max(values)) if len(values) else 0.0,
            float(np.percentile(values, 95)) if len(values) else 0.0)


def _better(prior, candidate):
    before = _free_turns(prior.points, prior.corridor.pin_indices)
    after = _free_turns(candidate, prior.corridor.pin_indices)
    length_ok = base._path_length(candidate) <= 1.03 * prior.length
    quality = ((after[1] < before[1] - 0.25 and after[0] <= before[0] + 1.0) or
               (after[0] < before[0] - 1.0 and after[1] <= before[1] + 0.25))
    return bool(length_ok and quality)


def _rejection_message(valid):
    return "transverse candidate did not improve turn quality" if valid else "transverse candidate is unsafe"


def _failed(prior, mode, message):
    return V3TransverseResult(points=prior.points, mode=mode, termination=prior.termination,
                              message=message, first_pass=prior)


def _ms(started):
    return 1000.0 * (perf_counter() - started)
