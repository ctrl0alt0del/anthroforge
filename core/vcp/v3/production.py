"""Stable production facade for the accepted Fiber V3 chain."""

from os import environ

from ..v2.collision import (clear_native_collision_world_cache,
                            clear_triangle_snapshot_cache, collision_backend_status,
                            triangle_snapshot_cache_stats)
from ..v2.structural import clear_structural_cache, structural_cache_stats
from .manifest import V3_ACCEPTED_FEATURES, V3_ACCEPTED_REFERENCE
from .policy import V3_PRODUCTION_POLICY, V3ProductionPolicy, V3ShortcutMode
from .solver import begin_v3_session, solve_v3_session


V3_PRODUCTION_VERSION = "fiber-v3-production-2"
V3_NATIVE_SESSION_ENV = "AF_FIBER_V3_NATIVE_SESSION"


def solve_v3(request, snapshot=None, preview=False, checkpoint_steps=0,
             use_planner=True, policy=V3_PRODUCTION_POLICY, native_session=None):
    return solve_v3_session(request, snapshot, preview, checkpoint_steps, use_planner,
                            policy, _native_session_enabled(native_session))


def begin_v3(request, snapshot=None, preview=False, checkpoint_steps=0,
             use_planner=True, policy=V3_PRODUCTION_POLICY, native_session=None):
    return begin_v3_session(request, snapshot, preview, checkpoint_steps, use_planner,
                            policy, _native_session_enabled(native_session))


def _native_session_enabled(explicit):
    if explicit is not None: return bool(explicit)
    raw = environ.get(V3_NATIVE_SESSION_ENV, "1").strip()
    if raw not in ("0", "1"): raise ValueError(f"{V3_NATIVE_SESSION_ENV} must be 0 or 1")
    return raw == "1"


def v3_backend_status():
    return collision_backend_status()


def clear_v3_caches():
    for clear in _cache_clearers(): clear()


def v3_cache_stats():
    return {"structural": structural_cache_stats(),
            "triangles": triangle_snapshot_cache_stats(),
            "policy": V3_PRODUCTION_POLICY.fingerprint()}


def _cache_clearers():
    return clear_structural_cache, clear_triangle_snapshot_cache, clear_native_collision_world_cache
