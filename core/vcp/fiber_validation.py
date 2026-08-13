"""Resumable accepted-state and final Fiber validation."""

from dataclasses import dataclass
from math import isfinite
from time import perf_counter

from mathutils import Vector

from .fiber_collision import (
    _QUERY_CACHE_LIMIT, _cached_push_result, _point_query_key, _push_out_one,
)

@dataclass
class FiberValidationWork:
    iterator: object
    done: bool = False
    result: object = None


def begin_post_validation(session, payload):
    return FiberValidationWork(_post_validation_steps(session, payload))


def begin_final_validation(session):
    iterator = _loop_final_steps(session) if session.loop else _open_final_steps(session)
    return FiberValidationWork(iterator)


def advance_validation(work, deadline):
    ran = False
    while not work.done and (not ran or perf_counter() < deadline):
        _advance_once(work)
        ran = True
    return work.done


def _advance_once(work):
    try:
        next(work.iterator)
    except StopIteration as stop:
        work.result, work.done = stop.value, True


def _post_validation_steps(session, payload):
    level, solver = session.level, session.solver
    _set_guards(level, payload)
    solver._clear_owner_zone_cache(payload[0])
    colliders = solver._active_colliders(
        session.oracle, level.nodes, payload[0]["margin"])
    clear = yield from _snapshot_clear_steps(
        solver, level.nodes, session.oracle, colliders, payload[0],
        session.loop, not session.loop, level.pinned)
    safe = _updated_safe(solver, level.nodes, level.safe, clear, session.loop)
    level.prev_nodes = [point.copy() for point in level.nodes]
    level.colliders, level.safe = colliders, safe
    return payload


def _set_guards(level, payload):
    _local, guards, _disp, _pen, alpha = payload
    level.guards = guards if alpha >= 0.999999 else {}


def _updated_safe(solver, nodes, safe, clear, cyclic):
    if not clear:
        return safe
    candidate = [point.copy() for point in nodes]
    return candidate if solver._snapshot_better(candidate, safe, cyclic) else safe


def _snapshot_clear_steps(solver, nodes, oracle, colliders, params, cyclic, skip_ends, pinned):
    local = dict(params, segment_collisions=True)
    if not (yield from _segments_clear_steps(
            solver, nodes, oracle, colliders, local, cyclic, skip_ends)):
        return False
    return (yield from _free_nodes_clear_steps(
        solver, nodes, oracle, colliders, params, cyclic, skip_ends, pinned))


def _segments_clear_steps(solver, nodes, oracle, colliders, params, cyclic, skip_ends):
    if not params["segment_collisions"]:
        return True
    key, cache = _state_cache(solver, nodes, colliders, params, cyclic, skip_ends, "clear")
    if cache is not None and key in cache:
        return bool(cache[key])
    result = yield from _uncached_segments_clear(
        solver, nodes, oracle, colliders, params, cyclic, skip_ends)
    None if cache is None else cache.__setitem__(key, result)
    return result


def _uncached_segments_clear(solver, nodes, oracle, colliders, params, cyclic, skip_ends):
    pairs = solver._clear_segment_pairs(len(nodes), cyclic, skip_ends)
    zones = yield from _owner_zones_steps(
        solver, nodes, oracle, colliders, params)
    for first, second in pairs:
        blocked = yield from _pair_blocked_steps(
            solver, nodes, first, second, oracle, colliders, params, zones)
        if blocked:
            return False
    return True


def _free_nodes_clear_steps(solver, nodes, oracle, colliders, params, cyclic, skip_ends, pinned):
    indices = solver._free_node_indices(len(nodes), pinned, cyclic, skip_ends)
    zones = yield from _owner_zones_steps(
        solver, nodes, oracle, colliders, params)
    for index in indices:
        cols = solver._node_colliders(
            nodes, index, oracle, colliders, params, zones)
        penetration = yield from _penetration_steps(nodes[index], oracle, cols)
        if penetration > 0.0:
            return False
    return True


def _state_cache(solver, nodes, colliders, params, cyclic, skip_ends, name):
    key = solver._state_penetration_key(nodes, colliders, params, cyclic, skip_ends)
    context = solver._collision_context(params)
    cache = None if context is None else context.setdefault(name, {})
    return key, cache


def _open_final_steps(session):
    level, solver = session.level, session.solver
    safe = yield from _restore_choice_steps(
        solver, level.safe, level.first_safe, session.oracle,
        level.colliders, level.params, False, True)
    yield from _restore_safe_steps(
        solver, level.nodes, safe, session.oracle, level.colliders,
        level.params, False, True)
    solver._restore_pins(level.nodes, level.targets)
    residual = yield from _exact_open_residual_steps(session, level.nodes)
    _set_final_residual(level, residual)
    if session.route_seed is not None and not _safe_open_residual(level, residual):
        yield from _try_seed_fallback_steps(session)
    return level.converged


def _exact_open_residual_steps(session, nodes):
    if not _finite_nodes(nodes):
        return float("inf")
    return (yield from _final_residual_steps(
        session.solver, nodes, session.oracle, session.level.params, False))


def _safe_open_residual(level, residual):
    return isfinite(float(residual)) and float(residual) < float(level.params["eps_pen"])


def _try_seed_fallback_steps(session):
    candidate = _seed_candidate(session)
    residual = yield from _exact_open_residual_steps(session, candidate)
    if not _safe_open_residual(session.level, residual):
        return False
    displacement = session.solver._max_displacement(candidate, session.level.nodes)
    session.solver._copy_nodes(session.level.nodes, candidate)
    session.level.converged = False
    session.level.max_disp = max(session.level.max_disp, float(displacement))
    session.level.max_pen = float(residual)
    _record_fallback_colliders(session, candidate)
    return True


def _seed_candidate(session):
    level, solver = session.level, session.solver
    candidate = solver._resample_polyline(session.route_seed, len(level.nodes))
    solver._restore_pins(candidate, level.targets)
    return candidate


def _record_fallback_colliders(session, candidate):
    active = session.solver._active_colliders(
        session.oracle, candidate, session.level.params["margin"])
    session.level.colliders = active
    session.active_count = max(session.active_count, len(active))


def _finite_nodes(nodes):
    return bool(nodes) and all(all(isfinite(float(value)) for value in point) for point in nodes)


def _loop_final_steps(session):
    level, solver = session.level, session.solver
    if not level.converged:
        safe = yield from _restore_choice_steps(
            solver, level.safe, level.first_safe, session.oracle,
            level.colliders, level.params, True, False)
        yield from _restore_safe_steps(
            solver, level.nodes, safe, session.oracle, level.colliders,
            level.params, True, False)
    residual = yield from _final_residual_steps(
        solver, level.nodes, session.oracle, level.params, True)
    _set_final_residual(level, residual)
    return level.converged


def _set_final_residual(level, residual):
    level.converged = bool(level.converged and residual < level.params["eps_pen"])
    level.max_pen = float(residual)


def _restore_choice_steps(solver, safe, fallback, oracle, colliders, params, cyclic, skip_ends):
    selected = yield from _valid_snapshot_steps(
        solver, safe, oracle, colliders, params, cyclic, skip_ends)
    if selected is not None:
        return selected
    return (yield from _valid_snapshot_steps(
        solver, fallback, oracle, colliders, params, cyclic, skip_ends))


def _valid_snapshot_steps(solver, snapshot, oracle, colliders, params, cyclic, skip_ends):
    if snapshot is None:
        return None
    active = solver._snapshot_colliders(
        oracle, snapshot, colliders, params["margin"])
    clear = yield from _segments_clear_steps(
        solver, snapshot, oracle, active, params, cyclic, skip_ends)
    return snapshot if clear else None


def _restore_safe_steps(solver, nodes, safe, oracle, colliders, params, cyclic, skip_ends):
    if safe is None:
        return
    active = solver._snapshot_colliders(
        oracle, nodes, colliders, params["margin"])
    clear = yield from _segments_clear_steps(
        solver, nodes, oracle, active, params, cyclic, skip_ends)
    if clear and not solver._snapshot_better(safe, nodes, cyclic):
        return
    solver._copy_nodes(nodes, safe)


def _final_residual_steps(solver, nodes, oracle, params, cyclic):
    solver._clear_owner_zone_cache(params)
    colliders = solver._active_colliders(oracle, nodes, params["margin"])
    local = dict(params, segment_collisions=True)
    zones = yield from _owner_zones_steps(
        solver, nodes, oracle, colliders, local)
    node_pen = yield from _node_residual_steps(
        solver, nodes, oracle, colliders, local, zones)
    edge_pen = yield from _edge_residual_steps(
        solver, nodes, oracle, colliders, local, zones, cyclic)
    return max(float(node_pen), float(edge_pen))


def _node_residual_steps(solver, nodes, oracle, colliders, params, zones):
    maximum = 0.0
    for index, point in enumerate(nodes):
        cols = solver._node_colliders(
            nodes, index, oracle, colliders, params, zones)
        penetration = yield from _penetration_steps(point, oracle, cols)
        maximum = max(maximum, penetration)
    return maximum


def _edge_residual_steps(solver, nodes, oracle, colliders, params, zones, cyclic):
    key, cache = _state_cache(solver, nodes, colliders, params, cyclic, False, "pen")
    if cache is not None and key in cache:
        return float(cache[key])
    maximum = yield from _uncached_edge_residual(
        solver, nodes, oracle, colliders, params, zones, cyclic)
    None if cache is None else cache.__setitem__(key, maximum)
    return maximum


def _uncached_edge_residual(solver, nodes, oracle, colliders, params, zones, cyclic):
    maximum = 0.0
    for first, second in solver._clear_segment_pairs(len(nodes), cyclic, False):
        penetration = yield from _pair_penetration_steps(
            solver, nodes, first, second, oracle, colliders, params, zones)
        maximum = max(maximum, penetration)
    return maximum


def _pair_blocked_steps(solver, nodes, first, second, oracle, colliders, params, zones):
    cols = solver._pair_colliders(
        nodes, first, second, oracle, colliders, params, zones)
    if solver._no_real_colliders(oracle, cols):
        return False
    if solver._cached_segment_ray(nodes[first], nodes[second], oracle, cols, params):
        return True
    for value in solver._segment_samples():
        point = nodes[first].lerp(nodes[second], value)
        if (yield from _penetration_steps(point, oracle, cols)) > 0.0:
            return True
    return False


def _pair_penetration_steps(solver, nodes, first, second, oracle, colliders, params, zones):
    cols = solver._pair_colliders(
        nodes, first, second, oracle, colliders, params, zones)
    if solver._no_real_colliders(oracle, cols):
        return 0.0
    samples = solver._segment_samples_for_cached(
        nodes[first], nodes[second], oracle, cols, params)
    maximum = yield from _sample_max_steps(
        nodes[first], nodes[second], samples, oracle, cols)
    if not solver._uses_v2(params):
        return maximum
    return (yield from _v2_pair_penetration(
        solver, nodes[first], nodes[second], oracle, cols, params, maximum))


def _sample_max_steps(start, end, samples, oracle, colliders):
    maximum = 0.0
    for value in samples:
        penetration = yield from _penetration_steps(
            start.lerp(end, value), oracle, colliders)
        maximum = max(maximum, penetration)
    return maximum


def _v2_pair_penetration(solver, start, end, oracle, colliders, params, sample_pen):
    first = yield from _penetration_steps(start, oracle, colliders)
    second = yield from _penetration_steps(end, oracle, colliders)
    blocked = solver._cached_segment_ray(start, end, oracle, colliders, params)
    return 0.0 if max(first, second) <= 0.0 and not blocked else sample_pen


def _penetration_steps(point, oracle, colliders):
    cols = tuple(colliders or ())
    if not cols and hasattr(oracle, "active_colliders_for_polyline"):
        return 0.0
    cached = _cached_push(oracle, point, cols)
    if cached is not None:
        return float(cached[1])
    pushed, maximum = Vector(point), 0.0
    for collider in cols:
        pushed, maximum = _push_out_one(oracle, collider, pushed, maximum)
        yield None
    _store_push(oracle, point, cols, pushed, maximum)
    return float(maximum)


def _cached_push(oracle, point, colliders):
    cache = getattr(oracle, "_push_cache", None)
    if cache is None:
        return None
    key = _point_query_key(point, colliders)
    if key not in cache:
        return None
    value = cache.pop(key)
    cache[key] = value
    return value


def _store_push(oracle, point, colliders, pushed, penetration):
    cache = getattr(oracle, "_push_cache", None)
    if cache is None:
        return
    cache[_point_query_key(point, colliders)] = _cached_push_result(
        (pushed, penetration))
    while len(cache) > _QUERY_CACHE_LIMIT:
        cache.popitem(last=False)


def _owner_zones_steps(solver, nodes, oracle, colliders, params):
    owners = solver._pin_owner_items(nodes, params)
    key = solver._owner_zone_key(nodes, colliders, owners)
    context = solver._collision_context(params)
    cache = None if context is None else context.setdefault("zones", {})
    if cache is not None and key in cache:
        return cache[key]
    zones = yield from _compute_zones_steps(
        solver, nodes, oracle, colliders, owners)
    None if cache is None else cache.__setitem__(key, zones)
    return zones


def _compute_zones_steps(solver, nodes, oracle, colliders, owners):
    zones = {}
    by_sid = {str(collider["sid"]): collider for collider in tuple(colliders or ())}
    for index, owner in owners:
        if owner and owner in by_sid:
            zone = yield from _pin_zone_steps(
                nodes, oracle, by_sid[owner], int(index))
            zones.setdefault(owner, []).append(zone)
    return {sid: tuple(values) for sid, values in zones.items()}


def _pin_zone_steps(nodes, oracle, collider, index):
    pin = max(0, min(len(nodes) - 1, int(index)))
    left = yield from _zone_left_steps(nodes, oracle, collider, pin)
    right = yield from _zone_right_steps(nodes, oracle, collider, pin)
    return left, right


def _zone_left_steps(nodes, oracle, collider, pin):
    index = int(pin)
    while index > 0:
        penetration = yield from _penetration_steps(
            nodes[index - 1], oracle, (collider,))
        if penetration <= 0.0:
            break
        index -= 1
    return index


def _zone_right_steps(nodes, oracle, collider, pin):
    index = int(pin)
    while index + 1 < len(nodes):
        penetration = yield from _penetration_steps(
            nodes[index + 1], oracle, (collider,))
        if penetration <= 0.0:
            break
        index += 1
    return index
