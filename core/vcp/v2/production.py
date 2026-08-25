"""Stable production facade for the accepted Fiber V2 chain."""

from .collision import (clear_native_collision_world_cache,
                        clear_triangle_snapshot_cache, collision_backend_status,
                        triangle_snapshot_cache_stats)
from .contact_core import begin_contact_core, solve_contact_core
from .structural import clear_structural_cache, structural_cache_stats


V2_PRODUCTION_VERSION = "fiber-v2-production-3"
V2_ACCEPTED_FEATURES = (
    "package-1-contracts", "package-2-banded-structural", "package-3-native-collision",
    "package-4.3-native-planner", "package-5.1-fused-contacts", "package-6.1-dispatch",
    "v2.1-route-reuse", "v2.2-request-identity", "v2.3-shared-world",
    "v2.4-batch-world", "pin-surface-recovery", "roadmap-corner-recovery",
    "owner-chord-containment-guard", "contained-surface-projection",
    "augmented-unilateral-contact", "infeasible-start-filter",
    "native-block-pentadiagonal", "limiting-contact-injection",
)


def solve_v2(request, snapshot=None, preview=False):
    return solve_contact_core(request, snapshot=snapshot, preview=preview)


def begin_v2(request, snapshot=None, preview=False):
    return begin_contact_core(request, snapshot=snapshot, preview=preview)


def v2_backend_status():
    return collision_backend_status()


def clear_v2_production_caches():
    for clear in _cache_clearers():
        clear()


def v2_production_cache_stats():
    names = ("structural", "triangles")
    return dict(zip(names, (reader() for reader in _cache_readers())))


def _cache_clearers():
    return (clear_structural_cache, clear_triangle_snapshot_cache,
            clear_native_collision_world_cache)


def _cache_readers():
    return structural_cache_stats, triangle_snapshot_cache_stats
