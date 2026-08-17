"""V2.3 shared-world and generation-topology cold-start experiment."""

from collections import OrderedDict
from dataclasses import dataclass, replace
from time import perf_counter

import numpy as np

from . import solver as p5
from . import solver_v21 as v21
from . import solver_v22 as v22
from .collision import (build_triangle_snapshot, cached_native_collision_world,
                        cached_triangle_snapshot, collision_backend_status,
                        triangle_snapshot_cache_stats)
from .contracts import V2Diagnostics, V2Quality, V2Result, V2Termination, V2Topology
from .planner import plan_reference_v43


V2_SOLVER_V23_VERSION = "fiber-v2.3-solver-1"
_ROUTE_CACHE_LIMIT = 128
_ROUTE_CACHE = OrderedDict()


@dataclass(frozen=True)
class _RouteRecord:
    signature: str
    anchors: tuple
    planner: object
    fresh: bool


@dataclass(frozen=True)
class V23Trace(v22.V22Trace):
    snapshot_ms: float = 0.0
    world_ms: float = 0.0
    topology_entries: int = 0
    shared_world: bool = False


def clear_v23_route_cache():
    _ROUTE_CACHE.clear()


def v23_route_cache_stats():
    return {"entries": len(_ROUTE_CACHE), "limit": _ROUTE_CACHE_LIMIT}


def solve_v23(request, snapshot=None, contact_weight=p5.DEFAULT_CONTACT_WEIGHT, preview=False):
    started = perf_counter(); signature, signature_ms = v22._timed_signature(request); topology = {}
    triangle, cache_hit, snapshot_ms = _snapshot(request, snapshot, topology)
    world, world_ms = _world(request, topology)
    planner, route_trace, policy = _planner(request, triangle, world, signature, bool(preview))
    if not planner.succeeded:
        return _failed(request, planner, started, contact_weight, route_trace, policy,
                       signature, signature_ms, cache_hit, snapshot_ms, world_ms, topology)
    state = v21._state(request, planner, triangle, contact_weight, route_trace, world)
    _set_state(state, signature, signature_ms, cache_hit, policy, snapshot_ms, world_ms, topology)
    termination, message = v21._solve_state(state)
    return _finish(state, termination, message, started)


def _snapshot(request, supplied, topology):
    started = perf_counter()
    if supplied is not None:
        return supplied, True, p5._elapsed(started)
    key = v22.v22_snapshot_key(request); before = triangle_snapshot_cache_stats()["hits"]
    value = cached_triangle_snapshot(request.colliders, key, topology) if key else build_triangle_snapshot(request.colliders, topology)
    return value, bool(key and triangle_snapshot_cache_stats()["hits"] > before), p5._elapsed(started)


def _world(request, topology):
    started = perf_counter(); key = v22.v22_snapshot_key(request)
    value = cached_native_collision_world(request.colliders, key, topology)
    return value, p5._elapsed(started)


def _planner(request, snapshot, world, signature, preview, cache=None):
    key = v21._lineage_key(request); record = _cache_get(key, cache)
    if v22._exact_allowed(record, signature, preview):
        return v21._exact_reuse(record.planner), (True, True, 0.0, 0), (record.fresh, False, False)
    if v22._property_allowed(request, record):
        planner = v21._exact_reuse(record.planner); _cache_put(key, request, signature, planner, True, cache)
        return planner, (True, False, 0.0, 0), (True, False, False)
    warped, elapsed = _preview_reuse(request, snapshot, record, preview)
    if warped is not None:
        _cache_put(key, request, signature, warped, False, cache)
        return warped, (True, False, elapsed, 0), (False, True, False)
    planner, runs = _full_plan(request, snapshot, world)
    if planner.succeeded: _cache_put(key, request, signature, planner, True, cache)
    return planner, (False, False, elapsed, runs), (True, False, bool(record and not preview))


def _preview_reuse(request, snapshot, record, preview):
    if not preview or request.settings.quality is not V2Quality.INTERACTIVE:
        return None, 0.0
    return v21._try_reuse(request, snapshot, record)


def _full_plan(request, snapshot, world):
    if _wide_direct(request, world):
        return plan_reference_v43(request, snapshot, 8.0, world), 1
    first = plan_reference_v43(request, snapshot, native_world=world)
    if not first.succeeded or first.mode.value != "ROADMAP":
        return first, 1
    second = plan_reference_v43(request, snapshot, 8.0, world)
    return replace(second, diagnostics=p5._merged_planner_diagnostics(first, second)), 2


def _wide_direct(request, world):
    if not request.colliders:
        return True
    points = np.asarray([anchor.point for anchor in request.anchors], dtype=np.float64)
    edges = v21._anchor_edges(len(points), request.settings.topology is V2Topology.CYCLIC)
    owners = tuple((request.anchors[a].owner_id, request.anchors[b].owner_id) for a, b in edges)
    span = max(8.0 * request.collision_policy.collision_radius, 1.0e-7)
    clearance = request.collision_policy.collision_radius - request.tolerances.clearance_slack
    return all(world.validate(points, edges, owners, span, clearance).clear)


def _cache_get(key, cache=None):
    rows = _ROUTE_CACHE if cache is None else cache; record = rows.get(key)
    if record is not None: rows.move_to_end(key)
    return record


def _cache_put(key, request, signature, planner, fresh, cache=None):
    rows = _ROUTE_CACHE if cache is None else cache
    anchors = tuple(tuple(anchor.point) for anchor in request.anchors)
    rows[key] = _RouteRecord(signature, anchors, planner, bool(fresh))
    rows.move_to_end(key)
    while len(rows) > _ROUTE_CACHE_LIMIT: rows.popitem(last=False)


def _set_state(state, signature, signature_ms, cache_hit, policy, snapshot_ms, world_ms, topology):
    state.v22_signature = signature; state.v22_signature_ms = signature_ms
    state.v22_cache_hit = cache_hit; state.v22_policy = policy
    state.v23_snapshot_ms = snapshot_ms; state.v23_world_ms = world_ms
    state.v23_topology_entries = len(topology)


def _finish(state, termination, message, started):
    checked = p5._timed_validation(state, state.points); diagnostics = p5._diagnostics(state, checked)
    validated = bool(checked.valid and np.isfinite(state.points).all())
    if not validated: termination, message = V2Termination.UNSAFE_OUTPUT, "final independent validation failed"
    result = _result(state, diagnostics, termination, validated, message)
    return p5.V2Package5Result(result, state.planner, _trace(state, started))


def _result(state, diagnostics, termination, validated, message):
    values = tuple(tuple(float(value) for value in row) for row in state.points)
    backend = collision_backend_status().version
    return V2Result(state.v22_signature, termination, values, diagnostics, validated,
                    state.planner.mode.value, message, V2_SOLVER_V23_VERSION, backend)


def _trace(state, started):
    base = v21._trace(state, started); fresh, warped, refresh = state.v22_policy
    return V23Trace(**vars(base), compact_identity=bool(v22.v22_snapshot_key(state.request)),
                    snapshot_cache_hit=state.v22_cache_hit, signature_ms=state.v22_signature_ms,
                    fresh_planner=fresh, preview_warp=warped, final_refresh=refresh,
                    snapshot_ms=state.v23_snapshot_ms, world_ms=state.v23_world_ms,
                    topology_entries=state.v23_topology_entries, shared_world=True)


def _failed(request, planner, started, weight, route, policy, signature, signature_ms,
            cache_hit, snapshot_ms, world_ms, topology):
    backend = collision_backend_status().version
    result = V2Result(signature, planner.termination, (), V2Diagnostics(), False,
                      planner.mode.value, planner.message, V2_SOLVER_V23_VERSION, backend)
    base = v21.V21Trace(total_ms=p5._elapsed(started), contact_weight=float(weight),
                        planner_reused=route[0], exact_route_hit=route[1],
                        reuse_validation_ms=route[2], planner_full_runs=route[3])
    trace = V23Trace(**vars(base), compact_identity=bool(v22.v22_snapshot_key(request)),
                     snapshot_cache_hit=cache_hit, signature_ms=signature_ms,
                     fresh_planner=policy[0], preview_warp=policy[1], final_refresh=policy[2],
                     snapshot_ms=snapshot_ms, world_ms=world_ms,
                     topology_entries=len(topology), shared_world=True)
    return p5.V2Package5Result(result, planner, trace)
