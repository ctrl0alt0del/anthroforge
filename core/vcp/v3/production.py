"""Stable production facade for the accepted Fiber V3 chain."""

from ..v2.collision import (clear_native_collision_world_cache,
                            clear_triangle_snapshot_cache, collision_backend_status,
                            triangle_snapshot_cache_stats)
from ..v2.structural import clear_structural_cache, structural_cache_stats
from .manifest import V3_ACCEPTED_FEATURES, V3_ACCEPTED_REFERENCE
from .policy import V3_PRODUCTION_POLICY, V3ProductionPolicy, V3ShortcutMode
from .solver import begin_v3_session, solve_v3_session


V3_PRODUCTION_VERSION = "fiber-v3-production-1"


def solve_v3(request, snapshot=None, preview=False, checkpoint_steps=0,
             use_planner=True, policy=V3_PRODUCTION_POLICY):
    return solve_v3_session(request, snapshot, preview, checkpoint_steps, use_planner, policy)


def begin_v3(request, snapshot=None, preview=False, checkpoint_steps=0,
             use_planner=True, policy=V3_PRODUCTION_POLICY):
    return begin_v3_session(request, snapshot, preview, checkpoint_steps, use_planner, policy)


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
