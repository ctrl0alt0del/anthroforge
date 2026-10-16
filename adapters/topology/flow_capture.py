"""Capture native muscle charts and explicit FLOW fibers in world space."""
import numpy as np
from .capture import _curve_points, _fiber_id, _mirror_role, _guide_sort_key
try:
    from ...core.topology.model import TopologyGuide
except ImportError:
    from core.topology.model import TopologyGuide


def unit(values):
    return values / np.maximum(np.linalg.norm(values, axis=-1, keepdims=True), 1e-12)


def capture_flow(root, scene, depsgraph, settings, regions=None):
    if settings.backend != "QUADWILD": return np.empty((0, 10)), (), ()
    samples, paths, warnings = [], [], []
    capture_muscles(root, scene, samples, paths, warnings, regions)
    selected = {f.id for f in root.af_vcp_system.fibers if f.topology_mode == "OPEN" and f.topology_flow_guide}
    for obj in sorted(scene.objects, key=_guide_sort_key):
        if not obj.get("af_fiber_proxy") or obj.get("af_root_name") != root.name: continue
        if _fiber_id(obj) not in selected: continue
        points = _curve_points(obj, depsgraph)[::3]
        if len(points) < 2: continue
        direction = unit(np.diff(points, axis=0)); mid = (points[:-1] + points[1:]) * .5
        samples.append(np.column_stack((mid, direction, np.zeros_like(mid), np.full(len(mid), len(samples)))))
        paths.append(TopologyGuide(len(paths), _fiber_id(obj), obj.name, _mirror_role(obj), points))
    return np.vstack(samples) if samples else np.empty((0, 10)), tuple(paths), tuple(warnings)


def capture_muscles(root, scene, samples, paths, warnings, regions=None):
    from .muscle_flow import material_patches
    regions = [] if regions is None else regions
    for muscle in sorted(root.af_vcp_system.muscles, key=lambda m: m.id):
        for role in muscle_roles(root, muscle):
            try:
                patches, branched = material_patches(root, scene, muscle, role)
                append_patches(muscle, role, patches, branched, samples, paths, regions)
            except (ValueError, RuntimeError) as error:
                warnings.append(f"Muscle FLOW unavailable for {muscle.name} ({role}): {error}")


def append_patches(muscle, role, patches, branched, samples, paths, regions):
    from anthroforge.core.topology.flow_patches import grid_samples
    for key, grid, flip, seam in patches:
        owner = len(samples)
        data = grid_samples(grid, owner, flip)
        if not len(data): raise ValueError("Muscle FLOW patch has no nondegenerate interior samples.")
        samples.append(data)
        regions.append(dict(owner=owner, muscle_id=muscle.id, name=muscle.name, role=role,
                            patch=key, branched=branched, seam=seam, samples=len(data)))
        if not branched:
            paths.append(TopologyGuide(len(paths), muscle.id, muscle.name, role, grid[len(grid)//2, ::3].copy()))


def muscle_roles(root, muscle):
    from anthroforge.core.visualization.mirror_rules import effective_rule_for_muscle
    rule = effective_rule_for_muscle(muscle, {f.id: f for f in root.af_vcp_system.fibers},
                                     {s.id: s for s in root.af_scp_system.scps})
    return ("SOURCE", "MIRROR") if rule is not None else ("SOURCE",)
