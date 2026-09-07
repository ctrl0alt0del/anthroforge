import json

from mathutils import Vector

from ..vcp.runtime_state import muscle_inflation_ctrl_world
from .fiber_sync_helpers import cached_fiber_points
from .muscle_sync_helpers import mark_inflation_ctrl_location
from .mirror_rules import axis_index, effective_rule_for_muscle


def collect_fiber_points(root, scene, fiber_props):
    from .fiber_sync import register_fiber_sync

    fsync = register_fiber_sync()
    vis_col = fsync._get_vis_collection(scene)
    if vis_col is None:
        return None
    out = []
    for f in fiber_props:
        pts = _fiber_points(scene, root, fsync, vis_col, f)
        if pts is None or len(pts) < 2:
            return None
        out.append(pts)
    return out


def _fiber_points(scene, root, fsync, vis_col, fiber):
    _ = fsync, vis_col
    return cached_fiber_points(scene, root.name, fiber.id)


def collect_muscle_rows(root, scene, muscle, fiber_props):
    rows = collect_fiber_points(root, scene, fiber_props)
    return _expanded_rows(root, muscle, rows)


def collect_surface_rows(root, scene, surface, fiber_props):
    rows = collect_fiber_points(root, scene, fiber_props)
    return _expanded_rows(root, surface, rows)


def _expanded_rows(root, muscle, rows):
    rule = _mirror_rule(root, muscle)
    if not _use_mirrored_rows(muscle) or not rows or rule is None or _rows_span_plane(rows, *rule):
        return rows
    return _mirror_expanded_rows(rows, *rule)


def _use_mirrored_rows(muscle):
    return bool(getattr(muscle, "use_mirrored_rows", False))


def _mirror_rule(root, muscle):
    return effective_rule_for_muscle(muscle, _fiber_map(root), _scp_map(root))


def _fiber_map(root):
    fibers = getattr(getattr(root, "af_vcp_system", None), "fibers", ())
    return {str(fiber.id or ""): fiber for fiber in fibers}


def _scp_map(root):
    scps = getattr(getattr(root, "af_scp_system", None), "scps", ())
    return {str(scp.id or ""): scp for scp in scps}


def _rows_span_plane(rows, axis, origin, eps=1.0e-6):
    distances = [_row_signed_distance(row, axis, origin) for row in tuple(rows or ())]
    return bool(distances and min(distances) < -eps and max(distances) > eps)


def _mirror_expanded_rows(rows, axis, origin):
    ordered = _ordered_rows(rows, axis, origin)
    mirrored = [_mirror_row(row, axis, origin) for row in ordered if abs(_row_signed_distance(row, axis, origin)) > 1.0e-6]
    return list(reversed(mirrored)) + list(ordered)


def _ordered_rows(rows, axis, origin):
    return sorted(tuple(rows or ()), key=lambda row: abs(_row_signed_distance(row, axis, origin)))


def _row_signed_distance(row, axis, origin):
    if not row:
        return 0.0
    values = [float(point[_axis_index(axis)]) - _axis_origin(origin, axis) for point in row]
    return sum(values) / float(len(values))


def _axis_index(axis):
    return axis_index(axis)


def _axis_origin(origin, axis):
    return float(origin[_axis_index(axis)]) if hasattr(origin, "__len__") else 0.0


def _mirror_row(row, axis, origin):
    return [Vector(_mirror_coords(point, axis, origin)) for point in row]


def _mirror_coords(point, axis, origin):
    values = [float(point[i]) for i in range(3)]
    idx = _axis_index(axis)
    values[idx] = (2.0 * _axis_origin(origin, axis)) - values[idx]
    return values


def ensure_inflation_ctrl(vis_col, root, muscle, find_inflation_ctrl_fn, create_inflation_ctrl_fn):
    target = Vector(muscle_inflation_ctrl_world(muscle))
    ctrl = find_inflation_ctrl_fn(vis_col, root.name, muscle.id)
    if ctrl is None:
        ctrl = create_inflation_ctrl_fn(vis_col, root, muscle.id)
    ctrl.location = target
    mark_inflation_ctrl_location(ctrl)
    ctrl.show_in_front = True
    ctrl.hide_render = True
    return ctrl
