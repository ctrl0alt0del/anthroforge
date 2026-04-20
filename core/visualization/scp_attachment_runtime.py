import bpy
from mathutils import Matrix, Vector
from mathutils.geometry import closest_point_on_tri


_APPLIED_MW_KEY = "af_scp_attach_applied_mw"
_EPS = 1.0e-6


def _as_id(value):
    return str(value or "")


def _as_bool(value, default=False):
    if value is None:
        return bool(default)
    return bool(value)


def _as_vec3(value, default):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return Vector(default)
    try:
        return Vector((float(value[0]), float(value[1]), float(value[2])))
    except Exception:
        return Vector(default)


def _set_prop_raw(prop, key, value):
    try:
        setattr(prop, key, value)
        return
    except Exception:
        pass
    try:
        prop[key] = value
        return
    except Exception:
        pass


def _vec3_close(a, b, eps=1.0e-7):
    av = _as_vec3(a, (0.0, 0.0, 0.0))
    bv = _as_vec3(b, (0.0, 0.0, 0.0))
    return (av - bv).length <= float(eps)


def _matrix_flat16(m):
    return [
        float(m[0][0]),
        float(m[0][1]),
        float(m[0][2]),
        float(m[0][3]),
        float(m[1][0]),
        float(m[1][1]),
        float(m[1][2]),
        float(m[1][3]),
        float(m[2][0]),
        float(m[2][1]),
        float(m[2][2]),
        float(m[2][3]),
        float(m[3][0]),
        float(m[3][1]),
        float(m[3][2]),
        float(m[3][3]),
    ]


def _is_matrix_close(a, b, eps=_EPS):
    if not isinstance(a, (list, tuple)) or not isinstance(b, (list, tuple)):
        return False
    if len(a) != 16 or len(b) != 16:
        return False
    for av, bv in zip(a, b):
        if abs(float(av) - float(bv)) > float(eps):
            return False
    return True


def _mark_applied_matrix(obj):
    try:
        obj[_APPLIED_MW_KEY] = _matrix_flat16(obj.matrix_world)
    except Exception:
        pass


def _is_runtime_applied_matrix(obj, eps=_EPS):
    raw = obj.get(_APPLIED_MW_KEY)
    if not isinstance(raw, (list, tuple)) or len(raw) != 16:
        return False
    cur = _matrix_flat16(obj.matrix_world)
    return _is_matrix_close(raw, cur, eps=eps)


def _find_source_scp_obj(scene, root_name, scp_id):
    sid = _as_id(scp_id)
    for obj in scene.objects:
        if (
            obj.type == "MESH"
            and obj.get("af_scp")
            and not obj.get("af_scp_mirror")
            and obj.get("af_root_name") == root_name
            and _as_id(obj.get("af_scp_id")) == sid
        ):
            return obj
    return None


def _children_depth_order(scp_by_id):
    depth_cache = {}

    def depth_of(sid):
        sid = _as_id(sid)
        if sid in depth_cache:
            return depth_cache[sid]
        scp = scp_by_id.get(sid)
        if scp is None:
            depth_cache[sid] = 0
            return 0
        pid = _as_id(getattr(scp, "parent_id", ""))
        if not pid or pid not in scp_by_id or pid == sid:
            depth_cache[sid] = 0
            return 0
        d = depth_of(pid) + 1
        depth_cache[sid] = d
        return d

    keys = list(scp_by_id.keys())
    keys.sort(key=lambda sid: (depth_of(sid), sid))
    return keys


def _closest_point_barycentric(a, b, c, p):
    v0 = b - a
    v1 = c - a
    v2 = p - a
    d00 = v0.dot(v0)
    d01 = v0.dot(v1)
    d11 = v1.dot(v1)
    d20 = v2.dot(v0)
    d21 = v2.dot(v1)
    denom = (d00 * d11) - (d01 * d01)
    if abs(denom) <= _EPS:
        return None
    v = ((d11 * d20) - (d01 * d21)) / denom
    w = ((d00 * d21) - (d01 * d20)) / denom
    u = 1.0 - v - w
    wts = [float(u), float(v), float(w)]
    # Numerical guard for tiny negatives.
    wts = [0.0 if abs(x) < 1.0e-8 else x for x in wts]
    s = wts[0] + wts[1] + wts[2]
    if abs(s) <= _EPS:
        return None
    return (wts[0] / s, wts[1] / s, wts[2] / s)


def _normalized(v, fallback):
    out = Vector(v)
    if out.length <= _EPS:
        return Vector(fallback)
    out.normalize()
    return out


def _basis_from_tangent_normal(tangent, normal):
    t = _normalized(tangent, (1.0, 0.0, 0.0))
    n = Vector(normal) - (t * Vector(normal).dot(t))
    if n.length <= _EPS:
        alt = Vector((0.0, 0.0, 1.0))
        if abs(t.dot(alt)) > 0.99:
            alt = Vector((0.0, 1.0, 0.0))
        n = alt - (t * alt.dot(t))
    n = _normalized(n, (0.0, 0.0, 1.0))
    b = _normalized(n.cross(t), (0.0, 1.0, 0.0))
    t = _normalized(b.cross(n), (1.0, 0.0, 0.0))
    return Matrix((t, b, n)).transposed(), t, n


def _build_mesh_surface_data(mesh_obj, depsgraph):
    obj_eval = mesh_obj.evaluated_get(depsgraph)
    mesh_eval = obj_eval.to_mesh()
    if mesh_eval is None:
        return None
    try:
        if len(mesh_eval.vertices) <= 0:
            return None
        mesh_eval.calc_loop_triangles()
        mw = obj_eval.matrix_world.copy()
        verts_world = [mw @ v.co for v in mesh_eval.vertices]
        triangles = [tuple(tri.vertices) for tri in mesh_eval.loop_triangles]
        return {"verts_world": verts_world, "triangles": triangles}
    finally:
        obj_eval.to_mesh_clear()


def _nearest_parent_param_from_world(parent_obj, target_world, depsgraph):
    data = _build_mesh_surface_data(parent_obj, depsgraph)
    if not data:
        return None
    verts = data["verts_world"]
    triangles = data["triangles"]
    if not triangles:
        return None

    best = None
    for tri in triangles:
        i0, i1, i2 = int(tri[0]), int(tri[1]), int(tri[2])
        if i0 < 0 or i1 < 0 or i2 < 0:
            continue
        if i0 >= len(verts) or i1 >= len(verts) or i2 >= len(verts):
            continue
        a = verts[i0]
        b = verts[i1]
        c = verts[i2]
        cp = closest_point_on_tri(target_world, a, b, c)
        if cp is None:
            continue
        d2 = (cp - target_world).length_squared
        if best is None or d2 < best["d2"]:
            best = {"d2": d2, "cp": cp, "tri": (i0, i1, i2), "abc": (a, b, c)}

    if best is None:
        return None

    a, b, c = best["abc"]
    w = _closest_point_barycentric(a, b, c, best["cp"])
    if w is None:
        return None
    return {"tri_vidx": best["tri"], "tri_weights": (float(w[0]), float(w[1]), float(w[2]))}


def _frame_from_parent_param(parent_obj, param, depsgraph):
    data = _build_mesh_surface_data(parent_obj, depsgraph)
    if not data:
        return None
    verts = data["verts_world"]

    tri = tuple(param.get("tri_vidx", (-1, -1, -1)))
    w = tuple(param.get("tri_weights", (1.0, 0.0, 0.0)))
    if len(tri) != 3 or len(w) != 3:
        return None

    i0, i1, i2 = int(tri[0]), int(tri[1]), int(tri[2])
    if i0 < 0 or i1 < 0 or i2 < 0:
        return None
    if i0 >= len(verts) or i1 >= len(verts) or i2 >= len(verts):
        return None

    a = verts[i0]
    b = verts[i1]
    c = verts[i2]
    p = (a * float(w[0])) + (b * float(w[1])) + (c * float(w[2]))

    t_raw = b - a
    n_raw = (b - a).cross(c - a)
    if t_raw.length <= _EPS:
        t_raw = parent_obj.matrix_world.to_3x3() @ Vector((1.0, 0.0, 0.0))
    if n_raw.length <= _EPS:
        n_raw = parent_obj.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))

    basis, tangent, normal = _basis_from_tangent_normal(t_raw, n_raw)
    return {"point_world": p, "basis_world": basis, "tangent_world": tangent, "normal_world": normal}


def _nearest_world_point_on_surface(mesh_obj, target_world, depsgraph):
    data = _build_mesh_surface_data(mesh_obj, depsgraph)
    if not data:
        return None
    verts = data["verts_world"]
    triangles = data["triangles"]
    if not triangles:
        return None

    best = None
    for tri in triangles:
        i0, i1, i2 = int(tri[0]), int(tri[1]), int(tri[2])
        if i0 < 0 or i1 < 0 or i2 < 0:
            continue
        if i0 >= len(verts) or i1 >= len(verts) or i2 >= len(verts):
            continue
        a = verts[i0]
        b = verts[i1]
        c = verts[i2]
        cp = closest_point_on_tri(target_world, a, b, c)
        if cp is None:
            continue
        d2 = (cp - target_world).length_squared
        if best is None or d2 < best["d2"]:
            best = {"d2": d2, "cp": cp}
    if best is None:
        return None
    return best["cp"]


def _capture_from_current_pose(root, scene, child_scp, parent_scp, child_obj, parent_obj, depsgraph):
    _ = root
    _ = scene
    _ = parent_scp

    if _as_bool(getattr(child_scp, "attach_initialized", False), default=False):
        prev_child_anchor_local = _as_vec3(
            getattr(child_scp, "attach_child_origin_local", (0.0, 0.0, 0.0)),
            (0.0, 0.0, 0.0),
        )
        target_world = child_obj.matrix_world @ prev_child_anchor_local
    else:
        target_world = child_obj.matrix_world.translation.copy()

    param = _nearest_parent_param_from_world(parent_obj, target_world, depsgraph)
    if param is None:
        return False

    frame = _frame_from_parent_param(parent_obj, param, depsgraph)
    if frame is None:
        return False

    point_world = frame["point_world"]
    tangent_world = frame["tangent_world"]
    normal_world = frame["normal_world"]

    child_anchor_world = _nearest_world_point_on_surface(child_obj, point_world, depsgraph)
    if child_anchor_world is None:
        child_anchor_world = point_world.copy()

    child_mw_inv = child_obj.matrix_world.inverted()
    child_origin_local = child_mw_inv @ child_anchor_world

    child_rot_world = child_obj.matrix_world.to_quaternion().to_matrix()
    child_rot_inv = child_rot_world.inverted()
    child_tangent_local = child_rot_inv @ tangent_world
    child_normal_local = child_rot_inv @ normal_world

    changed = False
    tri_vidx = tuple(int(v) for v in param["tri_vidx"])
    tri_weights = tuple(float(v) for v in param["tri_weights"])

    if tuple(getattr(child_scp, "attach_parent_tri_vidx", (-1, -1, -1))) != tri_vidx:
        _set_prop_raw(child_scp, "attach_parent_tri_vidx", tri_vidx)
        changed = True
    if not _vec3_close(getattr(child_scp, "attach_parent_tri_weights", (1.0, 0.0, 0.0)), tri_weights, eps=1.0e-7):
        _set_prop_raw(child_scp, "attach_parent_tri_weights", tri_weights)
        changed = True

    old_c = _as_vec3(getattr(child_scp, "attach_child_origin_local", (0.0, 0.0, 0.0)), (0.0, 0.0, 0.0))
    old_t = _as_vec3(getattr(child_scp, "attach_child_tangent_local", (1.0, 0.0, 0.0)), (1.0, 0.0, 0.0))
    old_n = _as_vec3(getattr(child_scp, "attach_child_normal_local", (0.0, 0.0, 1.0)), (0.0, 0.0, 1.0))

    if (old_c - child_origin_local).length > 1.0e-7:
        _set_prop_raw(
            child_scp,
            "attach_child_origin_local",
            (float(child_origin_local.x), float(child_origin_local.y), float(child_origin_local.z)),
        )
        changed = True
    if (old_t - child_tangent_local).length > 1.0e-7:
        _set_prop_raw(
            child_scp,
            "attach_child_tangent_local",
            (float(child_tangent_local.x), float(child_tangent_local.y), float(child_tangent_local.z)),
        )
        changed = True
    if (old_n - child_normal_local).length > 1.0e-7:
        _set_prop_raw(
            child_scp,
            "attach_child_normal_local",
            (float(child_normal_local.x), float(child_normal_local.y), float(child_normal_local.z)),
        )
        changed = True

    if not _as_bool(getattr(child_scp, "attach_initialized", False), default=False):
        _set_prop_raw(child_scp, "attach_initialized", True)
        changed = True

    return changed


def capture_dirty_scp_attachments(root, scene, dirty_scp_ids, source="", event_type=""):
    src = _as_id(source).lower()
    evt = _as_id(event_type).upper()
    if src != "depsgraph" or evt != "TRANSFORM":
        return set()
    if not dirty_scp_ids:
        return set()

    scp_by_id = {_as_id(s.id): s for s in root.af_scp_system.scps}
    depsgraph = bpy.context.evaluated_depsgraph_get()
    changed = set()

    for sid in sorted({_as_id(v) for v in set(dirty_scp_ids)}):
        child_scp = scp_by_id.get(sid)
        if child_scp is None:
            continue
        pid = _as_id(getattr(child_scp, "parent_id", ""))
        if not pid:
            continue
        parent_scp = scp_by_id.get(pid)
        if parent_scp is None:
            continue

        child_obj = _find_source_scp_obj(scene, root.name, sid)
        parent_obj = _find_source_scp_obj(scene, root.name, pid)
        if child_obj is None or parent_obj is None:
            continue

        # Ignore runtime-driven writes; capture only user-driven transforms.
        if _is_runtime_applied_matrix(child_obj):
            continue

        if _capture_from_current_pose(root, scene, child_scp, parent_scp, child_obj, parent_obj, depsgraph):
            changed.add(sid)

    return changed


def _build_child_basis_local(child_scp):
    t_local = _as_vec3(getattr(child_scp, "attach_child_tangent_local", (1.0, 0.0, 0.0)), (1.0, 0.0, 0.0))
    n_local = _as_vec3(getattr(child_scp, "attach_child_normal_local", (0.0, 0.0, 1.0)), (0.0, 0.0, 1.0))
    basis_local, _t, _n = _basis_from_tangent_normal(t_local, n_local)
    return basis_local


def _apply_one_attachment(root, scene, child_scp, parent_scp, child_obj, parent_obj, depsgraph):
    _ = root
    _ = scene
    _ = parent_scp
    tri = tuple(int(v) for v in getattr(child_scp, "attach_parent_tri_vidx", (-1, -1, -1)))
    w = tuple(float(v) for v in getattr(child_scp, "attach_parent_tri_weights", (1.0, 0.0, 0.0)))
    frame = _frame_from_parent_param(parent_obj, {"tri_vidx": tri, "tri_weights": w}, depsgraph)
    if frame is None:
        return False

    p_world = frame["point_world"]
    parent_basis = frame["basis_world"]
    child_origin_local = _as_vec3(getattr(child_scp, "attach_child_origin_local", (0.0, 0.0, 0.0)), (0.0, 0.0, 0.0))
    follow_rotation = _as_bool(getattr(child_scp, "attach_follow_rotation", True), default=True)
    scale_world = child_obj.matrix_world.to_scale()
    scaled_child_anchor_local = Vector(
        (
            float(child_origin_local.x) * float(scale_world.x),
            float(child_origin_local.y) * float(scale_world.y),
            float(child_origin_local.z) * float(scale_world.z),
        )
    )

    if follow_rotation:
        child_basis_local = _build_child_basis_local(child_scp)
        rot_world = parent_basis @ child_basis_local.inverted()
        rot_world = rot_world.normalized()
    else:
        rot_world = child_obj.matrix_world.to_quaternion().to_matrix()

    pos_world = p_world - (rot_world @ scaled_child_anchor_local)

    if follow_rotation:
        mw = Matrix.LocRotScale(pos_world, rot_world.to_quaternion(), scale_world)
    else:
        mw = child_obj.matrix_world.copy()
        mw.translation = pos_world

    if _is_matrix_close(_matrix_flat16(child_obj.matrix_world), _matrix_flat16(mw), eps=1.0e-7):
        return False

    child_obj.matrix_world = mw
    _mark_applied_matrix(child_obj)
    return True


def apply_scp_attachments(
    sync,
    root,
    scene,
    scp_by_id,
    target_scp_ids=None,
    source_parent_ids=None,
    gate_meta=None,
):
    _ = sync
    _ = gate_meta
    target_ids = None if target_scp_ids is None else {_as_id(v) for v in set(target_scp_ids)}
    parent_source_ids = {_as_id(v) for v in set(source_parent_ids or set()) if _as_id(v)}

    # Back-solve runs only when source parent transform/geometry changed.
    if not parent_source_ids:
        return set()

    depsgraph = bpy.context.evaluated_depsgraph_get()
    changed = set()
    active_parent_ids = set(parent_source_ids)

    order = _children_depth_order(scp_by_id)
    for sid in order:
        child_scp = scp_by_id.get(sid)
        if child_scp is None:
            continue
        pid = _as_id(getattr(child_scp, "parent_id", ""))
        if not pid:
            continue
        parent_scp = scp_by_id.get(pid)
        if parent_scp is None:
            continue

        if pid not in active_parent_ids:
            continue

        if target_ids is not None and sid not in target_ids and pid not in target_ids:
            continue

        child_obj = _find_source_scp_obj(scene, root.name, sid)
        parent_obj = _find_source_scp_obj(scene, root.name, pid)
        if child_obj is None or parent_obj is None:
            continue

        if not _as_bool(getattr(child_scp, "attach_initialized", False), default=False):
            _capture_from_current_pose(root, scene, child_scp, parent_scp, child_obj, parent_obj, depsgraph)

        if _apply_one_attachment(root, scene, child_scp, parent_scp, child_obj, parent_obj, depsgraph):
            changed.add(sid)
            active_parent_ids.add(sid)

    return changed
