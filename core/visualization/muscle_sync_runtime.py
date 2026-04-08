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

    if Vector(muscle.inflation_ctrl_world).length_squared == 0.0:
        m = len(base_points)
        n = len(base_points[0]) if m > 0 else 0
        if m > 0 and n > 0:
            ci = m // 2
            cj = n // 2
            p = base_points[ci][cj]
            muscle.inflation_ctrl_world = (p.x, p.y, p.z)

    target = Vector(muscle.inflation_ctrl_world)
    snapped, _n = nearest_on_mesh_surface_fn(base_obj, target)
    if snapped is not None:
        target = snapped
        muscle.inflation_ctrl_world = (target.x, target.y, target.z)

    ctrl.location = target
    ctrl.show_in_front = True
    ctrl.hide_render = True
    return ctrl
