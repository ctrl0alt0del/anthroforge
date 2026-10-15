"""Behavior-preserving adapter for the existing warm and rebuilt-skin paths."""
from copy import deepcopy
import numpy as np
from .strategy_guides import guide_sets
from .strategy_model import TopologyUpdateCandidate
from . import topology_solver as solver


class CurrentTopologyStrategy:
    name = "current"
    version = 1

    def solve(self, context):
        if context.settings:
            raise ValueError("The current topology strategy has no configurable solver settings.")
        return _rebind(context) if context.skin_update == "rebuilt" else _project(context)


def _project(context):
    old, skin, capture = context.topology, context.after_skin, context.capture
    before, after = guide_sets(old.statistics, capture.guides)
    if old.skin_binding is None or old.guide_binding is None:
        raise ValueError("Topology update requires persistent skin and guide bindings.")
    binding, guide = deepcopy(old.skin_binding), deepcopy(old.guide_binding)
    points, status, _report = solver.reproject_topology(old.vertices, old.quads,
        skin.vertices, skin.triangles, binding, guide, before, after, symmetry_plane=deepcopy(capture.plane))
    return _candidate(points, binding, guide, status)


def _rebind(context):
    old, skin, capture = context.topology, context.after_skin, context.capture
    guides = guide_sets(old.statistics, capture.guides)[1]
    points, binding, guide, status, _report = solver.project_and_rebind_topology(
        old.vertices, old.quads, skin.vertices, skin.triangles, old.face_regions,
        old.guide_indices, guides, context.predicted, deepcopy(capture.plane))
    return _candidate(points, binding, guide, status)


def _candidate(points, binding, guide, status):
    from .arap import arap_cache_stats
    return TopologyUpdateCandidate(points, np.arange(len(points), dtype=np.int64),
        binding, guide, bool(np.isfinite(points).all()), status.message,
        {"quality_valid": status.valid, "quality_message": status.message, "projection": solver.projection_stats(), "arap_cache": arap_cache_stats()})
