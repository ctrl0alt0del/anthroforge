"""Stable production facade for the accepted Fiber V2 chain."""

from dataclasses import replace

from .collision import (clear_native_collision_world_cache,
                        clear_triangle_snapshot_cache, collision_backend_status,
                        triangle_snapshot_cache_stats)
from .contact_sampled import clear_sampled_contact_cache, sampled_contact_cache_stats
from .contact_structural import clear_contact_factor_cache, contact_factor_cache_stats
from .solver_pin_smoothing import solve_pin_smoothing
from .solver_v21 import clear_v21_route_cache, v21_route_cache_stats
from .solver_v22 import clear_v22_route_cache, v22_route_cache_stats
from .solver_v23 import clear_v23_route_cache, v23_route_cache_stats
from .solver_v24 import clear_v24_route_cache, v24_route_cache_stats
from .structural import clear_structural_cache, structural_cache_stats


V2_PRODUCTION_VERSION = "fiber-v2-production-2"
V2_ACCEPTED_FEATURES = (
    "package-1-contracts", "package-2-banded-structural", "package-3-native-collision",
    "package-4.3-native-planner", "package-5.1-fused-contacts", "package-6.1-dispatch",
    "v2.1-route-reuse", "v2.2-request-identity", "v2.3-shared-world",
    "v2.4-batch-world", "pin-surface-recovery", "roadmap-corner-recovery",
    "owner-chord-containment-guard", "contained-surface-projection",
)


def solve_v2(request, snapshot=None, preview=False):
    package = solve_pin_smoothing(request, snapshot=snapshot, preview=preview)
    result = replace(package.result, engine_version=V2_PRODUCTION_VERSION)
    return replace(package, result=result)


def v2_backend_status():
    return collision_backend_status()


def clear_v2_production_caches():
    for clear in _cache_clearers():
        clear()


def v2_production_cache_stats():
    names = ("structural", "contact", "sampled", "triangles", "route21", "route22",
             "route23", "route24")
    return dict(zip(names, (reader() for reader in _cache_readers())))


def _cache_clearers():
    return (clear_structural_cache, clear_contact_factor_cache, clear_sampled_contact_cache,
            clear_triangle_snapshot_cache, clear_native_collision_world_cache,
            clear_v21_route_cache, clear_v22_route_cache, clear_v23_route_cache,
            clear_v24_route_cache)


def _cache_readers():
    return (structural_cache_stats, contact_factor_cache_stats, sampled_contact_cache_stats,
            triangle_snapshot_cache_stats, v21_route_cache_stats, v22_route_cache_stats,
            v23_route_cache_stats, v24_route_cache_stats)
