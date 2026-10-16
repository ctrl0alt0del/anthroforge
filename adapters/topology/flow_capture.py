"""Capture native muscle charts and explicit FLOW fibers in world space."""
import numpy as np
from .capture import _curve_points, _fiber_id, _mirror_role, _guide_sort_key
try:
    from ...core.topology.model import TopologyGuide
except ImportError:
    from core.topology.model import TopologyGuide


def unit(values):
    return values / np.maximum(np.linalg.norm(values, axis=-1, keepdims=True), 1e-12)


def chart_samples(chart, owner):
    rows, cols = chart.row_count, chart.column_count
    if rows < 2 or cols < 2 or len(chart.inflated_vertices) != rows * cols:
        raise ValueError("Muscle has no regular material chart; use explicit FLOW fibers.")
    grid = np.asarray(chart.inflated_vertices).reshape(rows, cols, 3)
    along, across = np.gradient(grid, axis=1), np.gradient(grid, axis=0)
    select = (slice(1, -1, 2), slice(1, -1, 3))
    points = grid[select].reshape(-1, 3)
    samples = np.column_stack((points, unit(along)[select].reshape(-1, 3),
                              unit(np.cross(across, along))[select].reshape(-1, 3), np.full(len(points), owner)))
    return samples, grid[rows // 2, ::3].copy()


def capture_flow(root, scene, depsgraph, settings):
    if settings.backend != "QUADWILD": return np.empty((0, 10)), (), ()
    samples, paths, warnings = [], [], []
    capture_muscles(root, scene, samples, paths, warnings)
    selected = {f.id for f in root.af_vcp_system.fibers if f.topology_mode == "OPEN" and f.topology_flow_guide}
    for obj in sorted(scene.objects, key=_guide_sort_key):
        if not obj.get("af_fiber_proxy") or obj.get("af_root_name") != root.name: continue
        if _fiber_id(obj) not in selected: continue
        points = _curve_points(obj, depsgraph)[::3]
        if len(points) < 2: continue
        direction = unit(np.diff(points, axis=0)); mid = (points[:-1] + points[1:]) * .5
        samples.append(np.column_stack((mid, direction, np.zeros_like(mid), np.full(len(mid), len(paths)))))
        paths.append(TopologyGuide(len(paths), _fiber_id(obj), obj.name, _mirror_role(obj), points))
    return np.vstack(samples) if samples else np.empty((0, 10)), tuple(paths), tuple(warnings)


def capture_muscles(root, scene, samples, paths, warnings):
    from anthroforge.adapters.deformation.muscles import material_chart
    for muscle in sorted(root.af_vcp_system.muscles, key=lambda m: m.id):
        for role in muscle_roles(root, muscle):
            try:
                data, line = chart_samples(material_chart(root, scene, muscle, role), len(paths))
                samples.append(data)
                paths.append(TopologyGuide(len(paths), muscle.id, muscle.name, role, line))
            except (ValueError, RuntimeError) as error:
                warnings.append(f"Muscle FLOW unavailable for {muscle.name} ({role}): {error}")


def muscle_roles(root, muscle):
    from anthroforge.core.visualization.mirror_rules import effective_rule_for_muscle
    rule = effective_rule_for_muscle(muscle, {f.id: f for f in root.af_vcp_system.fibers},
                                     {s.id: s for s in root.af_scp_system.scps})
    return ("SOURCE", "MIRROR") if rule is not None else ("SOURCE",)
