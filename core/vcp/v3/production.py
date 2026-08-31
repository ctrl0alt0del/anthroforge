"""Stable production facade for the accepted Fiber V3 chain."""

from os import environ

from ..v2.collision import (clear_native_collision_world_cache,
                            clear_triangle_snapshot_cache, collision_backend_status,
                            native_collision_cache_stats, triangle_snapshot_cache_stats)
from ..v2.structural import clear_structural_cache, structural_cache_stats
from .manifest import V3_ACCEPTED_FEATURES, V3_ACCEPTED_REFERENCE
from .policy import V3_PRODUCTION_POLICY, V3ProductionPolicy, V3ShortcutMode
from .solver import begin_v3_session, solve_v3_session
from .warm import clear_v3_warm_states, v3_warm_cache_stats


V3_PRODUCTION_VERSION = "fiber-v3-production-7"
V3_NATIVE_SESSION_ENV = "AF_FIBER_V3_NATIVE_SESSION"
V3_NATIVE_CONTROLLER_ENV = "AF_FIBER_V3_NATIVE_CONTROLLER"


def solve_v3(request, snapshot=None, preview=False, checkpoint_steps=0,
             use_planner=True, policy=V3_PRODUCTION_POLICY, native_session=None,
             native_controller=None):
    return solve_v3_session(request, snapshot, preview, checkpoint_steps, use_planner,
        policy, _native_session_enabled(native_session), _native_controller_enabled(native_controller))


def solve_v3_controller(request, snapshot=None, preview=False,
                        use_planner=True, policy=V3_PRODUCTION_POLICY):
    return solve_v3(request, snapshot, preview, 0, use_planner, policy, True, True)


def begin_v3(request, snapshot=None, preview=False, checkpoint_steps=0,
             use_planner=True, policy=V3_PRODUCTION_POLICY, native_session=None,
             native_controller=None):
    return begin_v3_session(request, snapshot, preview, checkpoint_steps, use_planner,
        policy, _native_session_enabled(native_session), _native_controller_enabled(native_controller))


def _native_session_enabled(explicit):
    if explicit is not None: return bool(explicit)
    raw = environ.get(V3_NATIVE_SESSION_ENV, "1").strip()
    if raw not in ("0", "1"): raise ValueError(f"{V3_NATIVE_SESSION_ENV} must be 0 or 1")
    return raw == "1"


def _native_controller_enabled(explicit=None):
    if explicit is not None: return bool(explicit)
    raw = environ.get(V3_NATIVE_CONTROLLER_ENV, "1").strip()
    if raw not in ("0", "1"): raise ValueError(f"{V3_NATIVE_CONTROLLER_ENV} must be 0 or 1")
    return raw == "1"


def v3_backend_status():
    return collision_backend_status()


def clear_v3_caches():
    for clear in _cache_clearers(): clear()


def v3_cache_stats():
    return {"structural": structural_cache_stats(),
            "triangles": triangle_snapshot_cache_stats(),
            "native_collision": native_collision_cache_stats(),
            "warm": v3_warm_cache_stats(),
            "policy": V3_PRODUCTION_POLICY.fingerprint()}


def _cache_clearers():
    return (clear_structural_cache, clear_triangle_snapshot_cache,
            clear_native_collision_world_cache, clear_v3_warm_states)
