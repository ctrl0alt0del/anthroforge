"""V2.4 native batch collision-world cold-start experiment."""

from collections import OrderedDict
from dataclasses import dataclass, replace
from time import perf_counter

import numpy as np

from . import solver as p5
from . import solver_v21 as v21
from . import solver_v22 as v22
from . import solver_v23 as v23
from .collision import (build_native_collision_world_batch, build_triangle_snapshot_known,
                        cached_known_triangle_snapshot, cached_native_collision_world_batch,
                        collision_backend_status, triangle_snapshot_cache_stats)
from .contracts import V2Diagnostics, V2Result, V2Termination
from .planner import V2PlannerMode, V2PlannerResult


V2_SOLVER_V24_VERSION = "fiber-v2.4-native-batch-1"
_ROUTE_CACHE = OrderedDict()


@dataclass(frozen=True)
class V24Trace(v23.V23Trace):
    native_batch: bool = True
    native_closed_count: int = 0


def clear_v24_route_cache():
    _ROUTE_CACHE.clear()


def v24_route_cache_stats():
    return {"entries": len(_ROUTE_CACHE), "limit": v23._ROUTE_CACHE_LIMIT}


def solve_v24(request, snapshot=None, contact_weight=p5.DEFAULT_CONTACT_WEIGHT, preview=False):
    started = perf_counter(); signature, signature_ms = v22._timed_signature(request)
    try:
        world, world_ms = _world(request)
        triangle, cache_hit, snapshot_ms = _snapshot(request, snapshot, world.closed_flags)
    except (OSError, RuntimeError, ValueError, AttributeError) as error:
        return _unavailable(request, signature, started, contact_weight, error)
    planner, route, policy = v23._planner(request, triangle, world, signature, bool(preview), _ROUTE_CACHE)
    if not planner.succeeded:
        return _failed(request, planner, started, contact_weight, route, policy, signature,
                       signature_ms, cache_hit, snapshot_ms, world_ms, world.closed_flags)
    state = _state(request, planner, triangle, contact_weight, route, world, signature,
                   signature_ms, cache_hit, policy, snapshot_ms, world_ms)
    termination, message = v21._solve_state(state)
    return _finish(state, termination, message, started)


def _state(request, planner, triangle, weight, route, world, signature, signature_ms,
           cache_hit, policy, snapshot_ms, world_ms):
    state = v21._state(request, planner, triangle, weight, route, world)
    v23._set_state(state, signature, signature_ms, cache_hit, policy, snapshot_ms, world_ms,
                   dict(enumerate(world.closed_flags)))
    state.v24_closed_count = sum(world.closed_flags)
    return state


def _world(request):
    started = perf_counter(); key = v22.v22_snapshot_key(request)
    value = (cached_native_collision_world_batch(request.colliders, key) if key else
             build_native_collision_world_batch(request.colliders))
    return value, p5._elapsed(started)


def _snapshot(request, supplied, closed):
    started = perf_counter()
    if supplied is not None:
        return supplied, True, p5._elapsed(started)
    key = v22.v22_snapshot_key(request); before = triangle_snapshot_cache_stats()["hits"]
    value = (cached_known_triangle_snapshot(request.colliders, key, closed) if key else
             build_triangle_snapshot_known(request.colliders, closed))
    hit = bool(key and triangle_snapshot_cache_stats()["hits"] > before)
    return value, hit, p5._elapsed(started)


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
                    state.planner.mode.value, message, V2_SOLVER_V24_VERSION, backend)


def _trace(state, started):
    base = v23._trace(state, started)
    return V24Trace(**vars(base), native_batch=True,
                    native_closed_count=int(state.v24_closed_count))


def _failed(request, planner, started, weight, route, policy, signature, signature_ms,
            cache_hit, snapshot_ms, world_ms, closed):
    base = v23._failed(request, planner, started, weight, route, policy, signature,
                       signature_ms, cache_hit, snapshot_ms, world_ms, dict(enumerate(closed)))
    result = replace(base.result, engine_version=V2_SOLVER_V24_VERSION)
    trace = V24Trace(**vars(base.trace), native_batch=True,
                     native_closed_count=sum(closed))
    return replace(base, result=result, trace=trace)


def _unavailable(request, signature, started, weight, error):
    message = f"native batch collision backend unavailable: {error}"
    planner = V2PlannerResult(V2Termination.BACKEND_UNAVAILABLE, V2PlannerMode.DIRECT,
                              message=message)
    result = V2Result(signature, V2Termination.BACKEND_UNAVAILABLE, (), V2Diagnostics(),
                      False, planner.mode.value, message, V2_SOLVER_V24_VERSION, "")
    trace = V24Trace(total_ms=p5._elapsed(started), contact_weight=float(weight))
    return p5.V2Package5Result(result, planner, trace)
