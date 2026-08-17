"""V2.2 generation-keyed snapshots and preview/final route policy."""

from collections import OrderedDict
from dataclasses import dataclass, replace
from time import perf_counter

import numpy as np

from . import solver as p5
from . import solver_v21 as v21
from .collision import (build_triangle_snapshot, cached_native_collision_world,
                        cached_triangle_snapshot, collision_backend_status,
                        triangle_snapshot_cache_stats)
from .contracts import (V2Diagnostics, V2Quality, V2Result, V2Termination,
                        V2Topology, stable_contract_signature)
from .planner import V2PlannerDiagnostics, plan_reference_v43


V2_SOLVER_V22_VERSION = "fiber-v2.2-solver-1"
_ROUTE_CACHE_LIMIT = 128
_ROUTE_CACHE = OrderedDict()


@dataclass(frozen=True)
class _RouteRecord:
    signature: str
    anchors: tuple
    planner: object
    fresh: bool


@dataclass(frozen=True)
class V22Trace(v21.V21Trace):
    compact_identity: bool = False
    snapshot_cache_hit: bool = False
    signature_ms: float = 0.0
    fresh_planner: bool = False
    preview_warp: bool = False
    final_refresh: bool = False


def clear_v22_route_cache():
    _ROUTE_CACHE.clear()


def v22_route_cache_stats():
    return {"entries": len(_ROUTE_CACHE), "limit": _ROUTE_CACHE_LIMIT}


def v22_snapshot_key(request):
    rows = tuple(_collider_key(item) for item in request.colliders)
    return (request.scene_id, request.root_id, rows) if all(item[2] for item in rows) else ()


def _collider_key(collider):
    return (collider.collider_id, collider.owner_id, collider.generation,
            len(collider.vertices), len(collider.triangles))


def v22_request_signature(request):
    key = v22_snapshot_key(request)
    return stable_contract_signature(_signature_payload(request, key)) if key else request.signature()


def _signature_payload(request, key):
    return {"contract": request.contract_version, "engine": request.engine_version,
            "scene": request.scene_id, "root": request.root_id, "source": request.source_revision,
            "settings": request.settings, "tolerances": request.tolerances,
            "collision": request.collision_policy, "anchors": request.anchors,
            "symmetry": (request.symmetry_mode, request.symmetry_axis, request.symmetry_origin),
            "colliders": key}


def solve_v22(request, snapshot=None, contact_weight=p5.DEFAULT_CONTACT_WEIGHT, preview=False):
    started = perf_counter(); signature, signature_ms = _timed_signature(request)
    triangle, cache_hit = _snapshot(request, snapshot)
    planner, route_trace, policy = _planner(request, triangle, signature, bool(preview))
    if not planner.succeeded:
        return _failed(request, planner, started, contact_weight, route_trace, policy,
                       signature, signature_ms, cache_hit)
    state = v21._state(request, planner, triangle, contact_weight, route_trace)
    state.v22_policy = policy; state.v22_signature = signature
    state.v22_signature_ms = signature_ms; state.v22_cache_hit = cache_hit
    termination, message = v21._solve_state(state)
    return _finish(state, termination, message, started)


def _timed_signature(request):
    started = perf_counter(); value = v22_request_signature(request)
    return value, p5._elapsed(started)


def _snapshot(request, supplied):
    if supplied is not None:
        return supplied, True
    key = v22_snapshot_key(request); before = triangle_snapshot_cache_stats()["hits"]
    snapshot = cached_triangle_snapshot(request.colliders, key) if key else build_triangle_snapshot(request.colliders)
    return snapshot, bool(key and triangle_snapshot_cache_stats()["hits"] > before)


def _planner(request, snapshot, signature, preview):
    key = v21._lineage_key(request); record = _cache_get(key)
    if _exact_allowed(record, signature, preview):
        return v21._exact_reuse(record.planner), (True, True, 0.0, 0), (record.fresh, False, False)
    if _property_allowed(request, record):
        planner = v21._exact_reuse(record.planner); _cache_put(key, request, signature, planner, True)
        return planner, (True, False, 0.0, 0), (True, False, False)
    warped, elapsed = _preview_reuse(request, snapshot, record, preview)
    if warped is not None:
        _cache_put(key, request, signature, warped, False)
        return warped, (True, False, elapsed, 0), (False, True, False)
    planner, runs = _full_plan(request, snapshot)
    if planner.succeeded:
        _cache_put(key, request, signature, planner, True)
    return planner, (False, False, elapsed, runs), (True, False, bool(record and not preview))


def _exact_allowed(record, signature, preview):
    return bool(record and record.signature == signature and (record.fresh or preview))


def _property_allowed(request, record):
    return bool(record and record.fresh and record.planner.mode.value != "SURFACE"
                and _same_anchors(request, record))


def _same_anchors(request, record):
    return tuple(tuple(anchor.point) for anchor in request.anchors) == record.anchors


def _preview_reuse(request, snapshot, record, preview):
    if not preview or request.settings.quality is not V2Quality.INTERACTIVE:
        return None, 0.0
    return v21._try_reuse(request, snapshot, record)


def _full_plan(request, snapshot):
    if _wide_direct(request):
        return plan_reference_v43(request, snapshot, owner_contact_factor=8.0), 1
    first = plan_reference_v43(request, snapshot)
    if not first.succeeded or first.mode.value != "ROADMAP":
        return first, 1
    second = plan_reference_v43(request, snapshot, owner_contact_factor=8.0)
    return replace(second, diagnostics=p5._merged_planner_diagnostics(first, second)), 2


def _wide_direct(request):
    if not request.colliders:
        return True
    points = np.asarray([anchor.point for anchor in request.anchors], dtype=np.float64)
    edges = v21._anchor_edges(len(points), request.settings.topology is V2Topology.CYCLIC)
    owners = tuple((request.anchors[a].owner_id, request.anchors[b].owner_id) for a, b in edges)
    span = max(8.0 * request.collision_policy.collision_radius, 1.0e-7)
    clearance = request.collision_policy.collision_radius - request.tolerances.clearance_slack
    world = cached_native_collision_world(request.colliders, v22_snapshot_key(request))
    return all(world.validate(points, edges, owners, span, clearance).clear)


def _cache_get(key):
    record = _ROUTE_CACHE.get(key)
    if record is not None:
        _ROUTE_CACHE.move_to_end(key)
    return record


def _cache_put(key, request, signature, planner, fresh):
    anchors = tuple(tuple(anchor.point) for anchor in request.anchors)
    _ROUTE_CACHE[key] = _RouteRecord(signature, anchors, planner, bool(fresh))
    _ROUTE_CACHE.move_to_end(key)
    while len(_ROUTE_CACHE) > _ROUTE_CACHE_LIMIT:
        _ROUTE_CACHE.popitem(last=False)


def _finish(state, termination, message, started):
    checked = p5._timed_validation(state, state.points); diagnostics = p5._diagnostics(state, checked)
    validated = bool(checked.valid and np.isfinite(state.points).all())
    if not validated:
        termination, message = V2Termination.UNSAFE_OUTPUT, "final independent validation failed"
    result = _result(state, diagnostics, termination, validated, message)
    return p5.V2Package5Result(result, state.planner, _trace(state, started))


def _result(state, diagnostics, termination, validated, message):
    values = tuple(tuple(float(value) for value in row) for row in state.points)
    backend = collision_backend_status().version
    return V2Result(state.v22_signature, termination, values, diagnostics, validated,
                    state.planner.mode.value, message, V2_SOLVER_V22_VERSION, backend)


def _trace(state, started):
    base = v21._trace(state, started); fresh, warped, refresh = state.v22_policy
    return V22Trace(**vars(base), compact_identity=bool(v22_snapshot_key(state.request)),
                    snapshot_cache_hit=state.v22_cache_hit, signature_ms=state.v22_signature_ms,
                    fresh_planner=fresh, preview_warp=warped, final_refresh=refresh)


def _failed(request, planner, started, weight, route_trace, policy, signature, signature_ms, cache_hit):
    backend = collision_backend_status().version
    result = V2Result(signature, planner.termination, (), V2Diagnostics(), False,
                      planner.mode.value, planner.message, V2_SOLVER_V22_VERSION, backend)
    base = v21.V21Trace(total_ms=p5._elapsed(started), contact_weight=float(weight),
                        planner_reused=route_trace[0], exact_route_hit=route_trace[1],
                        reuse_validation_ms=route_trace[2], planner_full_runs=route_trace[3])
    trace = V22Trace(**vars(base), compact_identity=bool(v22_snapshot_key(request)),
                     snapshot_cache_hit=cache_hit, signature_ms=signature_ms,
                     fresh_planner=policy[0], preview_warp=policy[1], final_refresh=policy[2])
    return p5.V2Package5Result(result, planner, trace)
