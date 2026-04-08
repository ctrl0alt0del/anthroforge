import json
from mathutils import Vector


def collect_fiber_points(root, scene, fiber_props):
    from .fiber_sync import register_fiber_sync

    fsync = register_fiber_sync()
    vis_col = fsync._get_vis_collection(scene)
    if vis_col is None:
        return None

    out = []
    for f in fiber_props:
        fobj = fsync._find_fiber_proxy(vis_col, root.name, f.id)
        if fobj is None:
            return None

        raw = fobj.get("af_fiber_points_world", "")
        if not raw:
            return None

        try:
            arr = json.loads(raw)
            pts = [Vector((float(v[0]), float(v[1]), float(v[2]))) for v in arr]
        except Exception:
            return None

        if len(pts) < 2:
            return None

        out.append(pts)

    return out


def ensure_inflation_ctrl(
    vis_col,
    root,
    muscle,
    base_obj,
    base_points,
    find_inflation_ctrl_fn,
    create_inflation_ctrl_fn,
    nearest_on_mesh_surface_fn,
):
    ctrl = find_inflation_ctrl_fn(vis_col, root.name, muscle.id)
    if ctrl is None:
        ctrl = create_inflation_ctrl_fn(vis_col, root, muscle.id)
    _ensure_initial_ctrl_world(muscle, base_points)
    target = _snap_ctrl_to_surface(muscle, base_obj, nearest_on_mesh_surface_fn)
    ctrl.location = target
    ctrl.show_in_front = True
    ctrl.hide_render = True
    return ctrl


def _ensure_initial_ctrl_world(muscle, base_points):
    if Vector(muscle.inflation_ctrl_world).length_squared != 0.0:
        return
    rows = len(base_points)
    cols = len(base_points[0]) if rows > 0 else 0
    if rows <= 0 or cols <= 0:
        return
    p = base_points[rows // 2][cols // 2]
    muscle.inflation_ctrl_world = (p.x, p.y, p.z)


def _snap_ctrl_to_surface(muscle, base_obj, nearest_on_mesh_surface_fn):
    target = Vector(muscle.inflation_ctrl_world)
    snapped, _n = nearest_on_mesh_surface_fn(base_obj, target)
    if snapped is None:
        return target
    muscle.inflation_ctrl_world = (snapped.x, snapped.y, snapped.z)
    return snapped
