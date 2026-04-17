import json

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from ..deps.dirty_hints import dirty_hints_for
from ..id_utils import next_prefixed_id
from ..utils import get_af_root


_ATTACH_MODE = "surface_anchor_v1"


def _resolve_sync_inputs(root, scene):
    scene = scene or bpy.context.scene
    root = root or get_af_root(scene)
    if root is None or scene is None:
        return None, None
    return root, scene


def _is_marked_source_scp(obj, root_name):
    return bool(
        obj
        and obj.type == "MESH"
        and obj.get("af_scp")
        and not obj.get("af_scp_mirror")
        and obj.get("af_root_name") == root_name
    )


def _scp_prop_map(root):
    return {str(s.id): s for s in root.af_scp_system.scps}


def _find_marked_object(scene, root_name, scp_id):
    sid = str(scp_id or "")
    for obj in scene.objects:
        if _is_marked_source_scp(obj, root_name) and str(obj.get("af_scp_id") or "") == sid:
            return obj
    return None


def _set_prop_raw(scp_prop, key, value):
    try:
        scp_prop[key] = value
    except Exception:
        try:
            setattr(scp_prop, key, value)
        except Exception:
            pass


def _discover_marked_scps(root, scene):
    scp_by_id = _scp_prop_map(root)
    for obj in scene.objects:
        if not _is_marked_source_scp(obj, root.name):
            continue
        sid = str(obj.get("af_scp_id") or "")
        if sid and sid in scp_by_id:
            scp = scp_by_id[sid]
            if str(getattr(scp, "object_name", "") or "") != obj.name:
                _set_prop_raw(scp, "object_name", obj.name)
            continue

        new_id = sid if sid and sid not in scp_by_id else next_prefixed_id(root.af_scp_system.scps, "SCP")
        obj["af_scp_id"] = new_id
        scp = root.af_scp_system.scps.add()
        scp.id = new_id
        scp.name = obj.name
        scp.object_name = obj.name
        scp.parent_id = ""
        scp.attach_param = ""
        scp.attach_follow_parent_rotation = True
        scp.mirror_enabled = False
        scp.mirror_axis = "X"
        scp.mirror_origin = (0.0, 0.0, 0.0)
        scp_by_id[new_id] = scp


def _prune_invalid_scps(root, scene):
    to_remove = []
    scps = root.af_scp_system.scps
    for i, scp in enumerate(scps):
        sid = str(getattr(scp, "id", "") or "")
        obj = _find_marked_object(scene, root.name, sid)
        if obj is None:
            to_remove.append(i)
            continue
        if str(getattr(scp, "object_name", "") or "") != obj.name:
            _set_prop_raw(scp, "object_name", obj.name)
    for i in reversed(to_remove):
        scps.remove(i)


def _sync_parent_links(root, scene):
    scp_by_id = _scp_prop_map(root)
    for scp in root.af_scp_system.scps:
        obj = _find_marked_object(scene, root.name, scp.id)
        if obj is None:
            continue
        parent_id = ""
        parent = getattr(obj, "parent", None)
        if _is_marked_source_scp(parent, root.name):
            pid = str(parent.get("af_scp_id") or "")
            if pid in scp_by_id:
                parent_id = pid
        if str(getattr(scp, "parent_id", "") or "") != parent_id:
            _set_prop_raw(scp, "parent_id", parent_id)


def _normalize_active_index(root):
    idx = int(getattr(root.af_scp_system, "active_scp_index", -1))
    n = len(root.af_scp_system.scps)
    if n <= 0:
        root.af_scp_system.active_scp_index = -1
        return
    if idx < 0 or idx >= n:
        root.af_scp_system.active_scp_index = min(max(idx, 0), n - 1)


def _parse_attach_param(raw):
    txt = str(raw or "").strip()
    if not txt:
        return None
    try:
        data = json.loads(txt)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if str(data.get("mode", "")) != _ATTACH_MODE:
        return None
    return data


def _encode_attach_param(data):
    return json.dumps(dict(data or {}), separators=(",", ":"))


def _vec3(value, fallback=(0.0, 0.0, 0.0)):
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return Vector((float(value[0]), float(value[1]), float(value[2])))
        except Exception:
            return Vector(fallback)
    return Vector(fallback)


def _mat3(value):
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            m = Matrix(value)
            if m.row_size == 3 and m.col_size == 3:
                return m
        except Exception:
            pass
    return Matrix.Identity(3)


def _mat3_rows(m):
    return [
        [float(m[0][0]), float(m[0][1]), float(m[0][2])],
        [float(m[1][0]), float(m[1][1]), float(m[1][2])],
        [float(m[2][0]), float(m[2][1]), float(m[2][2])],
    ]


def _safe_normalize(v, fallback):
    out = v.copy()
    if out.length <= 1e-9:
        return fallback.copy()
    out.normalize()
    return out


def _frame_basis(normal_world, preferred_tangent=None):
    n = _safe_normalize(normal_world, Vector((0.0, 0.0, 1.0)))

    t = None
    if preferred_tangent is not None:
        proj = preferred_tangent - n * float(preferred_tangent.dot(n))
        if proj.length > 1e-9:
            t = proj
    if t is None:
        t = n.cross(Vector((0.0, 0.0, 1.0)))
        if t.length <= 1e-9:
            t = n.cross(Vector((0.0, 1.0, 0.0)))
    t = _safe_normalize(t, Vector((1.0, 0.0, 0.0)))

    b = _safe_normalize(n.cross(t), Vector((0.0, 1.0, 0.0)))
    t = _safe_normalize(b.cross(n), Vector((1.0, 0.0, 0.0)))
    return Matrix((t, b, n)).transposed()


def _nearest_surface(parent_obj, query_world):
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
    except Exception:
        depsgraph = None
    if depsgraph is None:
        return None

    try:
        bvh = BVHTree.FromObject(parent_obj, depsgraph)
    except Exception:
        bvh = None
    if bvh is None:
        return None

    target_local = parent_obj.matrix_world.inverted() @ query_world
    nearest = bvh.find_nearest(target_local)
    if nearest is None or nearest[0] is None:
        return None

    co_local, n_local, _idx, _dist = nearest
    anchor_world = parent_obj.matrix_world @ co_local

    n = n_local if n_local is not None else Vector((0.0, 0.0, 1.0))
    mw3 = parent_obj.matrix_world.to_3x3()
    normal_world = mw3.inverted_safe().transposed() @ n
    normal_world = _safe_normalize(normal_world, Vector((0.0, 0.0, 1.0)))

    return {
        "anchor_world": anchor_world,
        "normal_world": normal_world,
    }


def _capture_attachment(child_obj, parent_obj, follow_rotation, prev_desc=None):
    child_loc, child_rot, _child_scale = child_obj.matrix_world.decompose()
    prev_anchor = _vec3((prev_desc or {}).get("anchor_world"), (child_loc.x, child_loc.y, child_loc.z))

    nearest = _nearest_surface(parent_obj, child_loc)
    if nearest is None:
        nearest = _nearest_surface(parent_obj, prev_anchor)
    if nearest is None:
        return None

    pref_tangent = _vec3((prev_desc or {}).get("tangent_world"), (1.0, 0.0, 0.0))
    parent_basis = _frame_basis(nearest["normal_world"], preferred_tangent=pref_tangent)

    position_offset = parent_basis.inverted() @ (child_loc - nearest["anchor_world"])
    if follow_rotation:
        rotation_offset = parent_basis.inverted() @ child_rot.to_matrix()
    else:
        rotation_offset = Matrix.Identity(3)

    tangent_world = Vector((parent_basis[0][0], parent_basis[1][0], parent_basis[2][0]))

    return {
        "mode": _ATTACH_MODE,
        "anchor_world": [float(nearest["anchor_world"].x), float(nearest["anchor_world"].y), float(nearest["anchor_world"].z)],
        "normal_world": [float(nearest["normal_world"].x), float(nearest["normal_world"].y), float(nearest["normal_world"].z)],
        "tangent_world": [float(tangent_world.x), float(tangent_world.y), float(tangent_world.z)],
        "position_offset": [float(position_offset.x), float(position_offset.y), float(position_offset.z)],
        "rotation_offset": _mat3_rows(rotation_offset),
        "follow_rotation": bool(follow_rotation),
    }


def _apply_attachment(sync, child_obj, parent_obj, desc):
    follow_rotation = bool(desc.get("follow_rotation", True))

    anchor_hint = _vec3(desc.get("anchor_world"), tuple(child_obj.matrix_world.translation))
    nearest = _nearest_surface(parent_obj, anchor_hint)
    if nearest is None:
        return False, desc

    preferred_tangent = _vec3(desc.get("tangent_world"), (1.0, 0.0, 0.0))
    parent_basis = _frame_basis(nearest["normal_world"], preferred_tangent=preferred_tangent)

    position_offset = _vec3(desc.get("position_offset"), (0.0, 0.0, 0.0))
    rotation_offset = _mat3(desc.get("rotation_offset"))

    cur_loc, cur_rot, cur_scale = child_obj.matrix_world.decompose()
    _ = cur_loc

    new_loc = nearest["anchor_world"] + (parent_basis @ position_offset)
    new_rot = (parent_basis @ rotation_offset).to_quaternion() if follow_rotation else cur_rot
    new_mw = Matrix.LocRotScale(new_loc, new_rot, cur_scale)

    moved = _matrix_differs(child_obj.matrix_world, new_mw) or (not sync._is_synced_matrix(child_obj))
    if moved:
        child_obj.matrix_world = new_mw

    tangent_world = Vector((parent_basis[0][0], parent_basis[1][0], parent_basis[2][0]))
    out = dict(desc)
    out["anchor_world"] = [float(nearest["anchor_world"].x), float(nearest["anchor_world"].y), float(nearest["anchor_world"].z)]
    out["normal_world"] = [float(nearest["normal_world"].x), float(nearest["normal_world"].y), float(nearest["normal_world"].z)]
    out["tangent_world"] = [float(tangent_world.x), float(tangent_world.y), float(tangent_world.z)]
    out["follow_rotation"] = bool(follow_rotation)

    return moved, out


def _descriptor_changed(a, b, eps=1e-6):
    if not isinstance(a, dict) or not isinstance(b, dict):
        return True

    def vec_changed(k):
        va = a.get(k)
        vb = b.get(k)
        if not (isinstance(va, (list, tuple)) and isinstance(vb, (list, tuple)) and len(va) == len(vb)):
            return va != vb
        for xa, xb in zip(va, vb):
            try:
                if abs(float(xa) - float(xb)) > eps:
                    return True
            except Exception:
                return xa != xb
        return False

    scalar_keys = ("mode", "follow_rotation")
    vector_keys = ("anchor_world", "normal_world", "tangent_world", "position_offset")

    for k in scalar_keys:
        if a.get(k) != b.get(k):
            return True
    for k in vector_keys:
        if vec_changed(k):
            return True

    ra = a.get("rotation_offset")
    rb = b.get("rotation_offset")
    if not (isinstance(ra, (list, tuple)) and isinstance(rb, (list, tuple)) and len(ra) == 3 and len(rb) == 3):
        return ra != rb
    for row_a, row_b in zip(ra, rb):
        if not (isinstance(row_a, (list, tuple)) and isinstance(row_b, (list, tuple)) and len(row_a) == 3 and len(row_b) == 3):
            return row_a != row_b
        for xa, xb in zip(row_a, row_b):
            try:
                if abs(float(xa) - float(xb)) > eps:
                    return True
            except Exception:
                return xa != xb

    return False


def _matrix_differs(a, b, eps=1e-6):
    try:
        for r in range(4):
            for c in range(4):
                if abs(float(a[r][c]) - float(b[r][c])) > eps:
                    return True
    except Exception:
        return True
    return False


def _scp_depth(scp_id, scp_by_id):
    depth = 0
    seen = set()
    cur = str(scp_id or "")
    while cur and cur not in seen:
        seen.add(cur)
        parent = str(getattr(scp_by_id.get(cur), "parent_id", "") or "")
        if not parent or parent not in scp_by_id:
            break
        depth += 1
        cur = parent
    return depth


def _sorted_scp_ids(scp_by_id):
    ids = list(scp_by_id.keys())
    ids.sort(key=lambda sid: (_scp_depth(sid, scp_by_id), sid))
    return ids


def _sync_attachment_for_scp(sync, root, scene, scp_prop, scp_by_id):
    child_obj = _find_marked_object(scene, root.name, scp_prop.id)
    if child_obj is None:
        return

    parent_id = str(getattr(scp_prop, "parent_id", "") or "")
    if not parent_id:
        sync._mark_synced_matrix(child_obj)
        return

    parent_prop = scp_by_id.get(parent_id)
    if parent_prop is None:
        sync._mark_synced_matrix(child_obj)
        return

    parent_obj = _find_marked_object(scene, root.name, parent_prop.id)
    if parent_obj is None:
        sync._mark_synced_matrix(child_obj)
        return

    follow_rotation = bool(getattr(scp_prop, "attach_follow_parent_rotation", True))
    desc = _parse_attach_param(getattr(scp_prop, "attach_param", ""))

    user_moved_child = not sync._is_synced_matrix(child_obj)
    if desc is None or user_moved_child:
        new_desc = _capture_attachment(child_obj, parent_obj, follow_rotation=follow_rotation, prev_desc=desc)
        if new_desc is not None:
            _set_prop_raw(scp_prop, "attach_param", _encode_attach_param(new_desc))
            desc = new_desc

    if desc is None:
        sync._mark_synced_matrix(child_obj)
        return

    _moved, updated_desc = _apply_attachment(sync, child_obj, parent_obj, desc)
    if _descriptor_changed(desc, updated_desc):
        _set_prop_raw(scp_prop, "attach_param", _encode_attach_param(updated_desc))

    sync._mark_synced_matrix(child_obj)


def _axis_to_scale(axis):
    a = str(axis or "X").upper()
    if a == "Y":
        return (1.0, -1.0, 1.0)
    if a == "Z":
        return (1.0, 1.0, -1.0)
    return (-1.0, 1.0, 1.0)


def _mirror_matrix(axis="X", origin=(0.0, 0.0, 0.0)):
    o = origin if isinstance(origin, Vector) else Vector(origin)
    sx, sy, sz = _axis_to_scale(axis)
    s = Matrix.Diagonal((sx, sy, sz, 1.0))
    return Matrix.Translation(o) @ s @ Matrix.Translation(-o)


def _copy_mesh_data(src_obj, dst_obj):
    if src_obj.type != "MESH":
        return
    if dst_obj.type != "MESH" or dst_obj.data is None:
        return

    src = src_obj.data
    dst = dst_obj.data
    verts = [v.co.copy() for v in src.vertices]
    faces = [tuple(p.vertices) for p in src.polygons]
    dst.clear_geometry()
    dst.from_pydata(verts, [], faces)
    dst.update()


def _ensure_mirror_object(sync, scene, mirror_col, root_name, scp_id, src_obj):
    mir = sync._find_mirror_object(scene, root_name, scp_id)
    if mir is None:
        mesh = bpy.data.meshes.new(f"{src_obj.name}_AF_MIRROR_MESH")
        mir = bpy.data.objects.new(f"{src_obj.name}_AF_MIR", mesh)
        mirror_col.objects.link(mir)
        mir["af_scp"] = True
        mir["af_scp_mirror"] = True
        mir["af_root_name"] = root_name
        mir["af_source_scp_id"] = str(scp_id)
        mir.hide_select = True
    return mir


def _build_mirror_roles(scp_by_id):
    roles = {}

    def resolve(sid, trail):
        sid = str(sid or "")
        if not sid:
            return {"is_source": False, "is_target": False, "source_id": "", "propagate_source_id": ""}
        if sid in roles:
            return roles[sid]
        if sid in trail:
            roles[sid] = {"is_source": False, "is_target": False, "source_id": "", "propagate_source_id": ""}
            return roles[sid]

        scp = scp_by_id.get(sid)
        if scp is None:
            roles[sid] = {"is_source": False, "is_target": False, "source_id": "", "propagate_source_id": ""}
            return roles[sid]

        pid = str(getattr(scp, "parent_id", "") or "")
        parent_role = resolve(pid, trail | {sid}) if pid else {"is_source": False, "is_target": False, "source_id": "", "propagate_source_id": ""}
        parent_source = str(parent_role.get("propagate_source_id", "") or "")

        source_self = bool(getattr(scp, "mirror_enabled", False))
        if source_self:
            roles[sid] = {
                "is_source": True,
                "is_target": bool(parent_source),
                "source_id": str(parent_source or ""),
                "propagate_source_id": sid,
            }
        else:
            roles[sid] = {
                "is_source": False,
                "is_target": bool(parent_source),
                "source_id": str(parent_source or ""),
                "propagate_source_id": str(parent_source or ""),
            }
        return roles[sid]

    for sid in list(scp_by_id.keys()):
        resolve(sid, set())
    return roles


def _sync_mirrors(sync, root, scene, scp_by_id):
    mirror_col = sync._get_mirror_collection(scene)
    roles = _build_mirror_roles(scp_by_id)

    desired = set()
    for sid, role in roles.items():
        if not bool(role.get("is_target", False)):
            continue

        rule_source_id = str(role.get("source_id", "") or "")
        src_prop = scp_by_id.get(rule_source_id)
        if src_prop is None:
            continue

        source_obj = _find_marked_object(scene, root.name, sid)
        if source_obj is None:
            continue

        axis = str(getattr(src_prop, "mirror_axis", "X") or "X")
        origin = tuple(getattr(src_prop, "mirror_origin", (0.0, 0.0, 0.0)))

        mir = _ensure_mirror_object(sync, scene, mirror_col, root.name, sid, source_obj)
        if mir is None:
            continue

        _copy_mesh_data(source_obj, mir)
        mir.matrix_world = _mirror_matrix(axis=axis, origin=origin) @ source_obj.matrix_world
        mir["af_source_scp_id"] = str(sid)
        mir["af_root_name"] = root.name
        desired.add(str(sid))

    for obj in list(scene.objects):
        if not obj.get("af_scp_mirror"):
            continue
        if obj.get("af_root_name") != root.name:
            continue
        sid = str(obj.get("af_source_scp_id") or "")
        if sid in desired:
            continue
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data and data.users == 0 and isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)


def sync_root_to_scene(sync, root=None, scene=None, target_scp_ids=None):
    if sync._syncing:
        return

    root, scene = _resolve_sync_inputs(root, scene)
    if root is None:
        return

    sync._syncing = True
    try:
        _discover_marked_scps(root, scene)
        _prune_invalid_scps(root, scene)
        _sync_parent_links(root, scene)
        _normalize_active_index(root)

        scp_by_id = _scp_prop_map(root)
        ids_all = set(scp_by_id.keys())
        ids_target = ids_all if target_scp_ids is None else (set(target_scp_ids) & ids_all)

        for sid in _sorted_scp_ids(scp_by_id):
            if sid not in ids_target:
                continue
            _sync_attachment_for_scp(sync, root, scene, scp_by_id[sid], scp_by_id)

        _sync_mirrors(sync, root, scene, scp_by_id)

    finally:
        sync._syncing = False


def on_depsgraph_update(sync, scene, depsgraph):
    if sync._syncing:
        return

    root = get_af_root(scene)
    if root is None:
        return

    changed_ids = set()
    has_geometry = False

    for upd in depsgraph.updates:
        obj = upd.id
        if not isinstance(obj, bpy.types.Object):
            continue
        if not _is_marked_source_scp(obj, root.name):
            continue
        sid = str(obj.get("af_scp_id") or "")
        if sid:
            changed_ids.add(sid)
        has_geometry = has_geometry or bool(getattr(upd, "is_updated_geometry", False))

    if changed_ids:
        from .sync_runner import sync_from_dirty_hints

        sync_from_dirty_hints(
            root=root,
            scene=scene,
            dirty_hints=dirty_hints_for("SCP", changed_ids),
            source="depsgraph",
            event_type="GEOMETRY" if has_geometry else "TRANSFORM",
        )
