import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree


def matrix_to_flat(m):
    return [
        float(m[0][0]), float(m[0][1]), float(m[0][2]), float(m[0][3]),
        float(m[1][0]), float(m[1][1]), float(m[1][2]), float(m[1][3]),
        float(m[2][0]), float(m[2][1]), float(m[2][2]), float(m[2][3]),
        float(m[3][0]), float(m[3][1]), float(m[3][2]), float(m[3][3]),
    ]


def is_synced_matrix(obj, eps=1e-6):
    raw = obj.get("af_last_synced_mw")
    if not isinstance(raw, (list, tuple)) or len(raw) != 16:
        return False
    cur = matrix_to_flat(obj.matrix_world)
    for a, b in zip(cur, raw):
        if abs(float(a) - float(b)) > eps:
            return False
    return True


def is_user_translate_active():
    try:
        wm = bpy.context.window_manager
        ops = getattr(wm, "operators", None) or []
        for op in reversed(list(ops)):
            bid = getattr(op, "bl_idname", "") or ""
            if bid == "TRANSFORM_OT_translate":
                return True
            if bid == "TRANSFORM_OT_transform":
                mode = str(getattr(getattr(op, "properties", None), "mode", "") or "")
                if mode == "TRANSLATION":
                    return True
        return False
    except Exception:
        return False


def world_matrix_from_mesh_anchor(scp, parent_proxy, parent_local_point, child_local_point):
    anchor_world = parent_proxy.matrix_world @ parent_local_point
    rs = scp.local_rotation.to_4x4() @ Matrix.Diagonal((*scp.local_scale, 1.0))
    child_off = rs @ Vector((child_local_point.x, child_local_point.y, child_local_point.z, 1.0))
    obj_origin = anchor_world - Vector((child_off.x, child_off.y, child_off.z))
    return Matrix.Translation(obj_origin) @ rs


def safe_normalize(v, fallback):
    out = v.copy()
    if out.length <= 1e-8:
        return fallback.copy()
    out.normalize()
    return out


def frame_basis3(tangent, normal):
    t = safe_normalize(tangent, Vector((1.0, 0.0, 0.0)))
    n = normal - t * t.dot(normal)
    n = safe_normalize(n, Vector((0.0, 0.0, 1.0)))
    if abs(t.dot(n)) > 0.999:
        n = safe_normalize(t.cross(Vector((0.0, 1.0, 0.0))), Vector((0.0, 0.0, 1.0)))
    b = safe_normalize(n.cross(t), Vector((0.0, 1.0, 0.0)))
    n = safe_normalize(t.cross(b), Vector((0.0, 0.0, 1.0)))
    return Matrix((t, b, n)).transposed()


def nearest_parent_param(parent_scp, parent_proxy, target_world):
    params = parent_scp.shape.get_attach_params() or [0.0]
    best_param = params[0]
    best_d2 = None
    for p in params:
        lp = parent_scp.shape.compute_local_point(p)
        wp = parent_proxy.matrix_world @ lp
        d2 = (wp - target_world).length_squared
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best_param = p
    return best_param


def world_matrix_from_surface_frame(scp, parent_scp, parent_proxy, payload):
    parent_param = payload.get("parent_param", 0.0)
    child_origin_local = payload.get("child_origin_local", Vector((0.0, 0.0, 0.0)))
    child_tangent_local = payload.get("child_tangent_local", Vector((1.0, 0.0, 0.0)))
    child_normal_local = payload.get("child_normal_local", Vector((0.0, 0.0, 1.0)))

    p_origin_local, p_tangent_local, p_normal_local = parent_scp.shape.sample_attachment_frame_local(parent_param)
    mw = parent_proxy.matrix_world
    mw3 = mw.to_3x3()
    p_origin_world = mw @ p_origin_local
    p_tangent_world = mw3 @ p_tangent_local
    p_normal_world = mw3 @ p_normal_local

    parent_basis = frame_basis3(p_tangent_world, p_normal_world)
    child_basis_local = frame_basis3(child_tangent_local, child_normal_local)
    attach_rot = parent_basis @ child_basis_local.inverted()
    final_rot = attach_rot @ scp.local_rotation

    sx, sy, sz = float(scp.local_scale.x), float(scp.local_scale.y), float(scp.local_scale.z)
    child_off_world = final_rot @ (Matrix.Diagonal((sx, sy, sz)) @ child_origin_local)
    obj_origin = p_origin_world - child_off_world

    out = final_rot.to_4x4()
    out.translation = obj_origin
    return out


def nearest_mesh_point_local(obj, target_world, depsgraph):
    try:
        bvh = BVHTree.FromObject(obj, depsgraph)
    except Exception:
        return None
    if bvh is None:
        return None

    target_local = obj.matrix_world.inverted() @ target_world
    nearest = bvh.find_nearest(target_local)
    if nearest is None:
        return None

    co, _normal, _index, _dist = nearest
    if co is None:
        return None
    return co.copy()
