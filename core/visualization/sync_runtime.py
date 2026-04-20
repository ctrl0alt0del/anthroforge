import bpy
from mathutils import Matrix, Vector

from ..deps.dirty_hints import dirty_hints_for
from ..id_utils import next_prefixed_id
from ..utils import get_af_root
from .scp_attachment_runtime import apply_scp_attachments


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
        scp.attach_follow_rotation = True
        scp.attach_initialized = False
        scp.attach_parent_tri_vidx = (-1, -1, -1)
        scp.attach_parent_tri_weights = (1.0, 0.0, 0.0)
        scp.attach_child_origin_local = (0.0, 0.0, 0.0)
        scp.attach_child_tangent_local = (1.0, 0.0, 0.0)
        scp.attach_child_normal_local = (0.0, 0.0, 1.0)
        scp.mirror_enabled = False
        scp.mirror_axis = "X"
        scp.mirror_origin = (0.0, 0.0, 0.0)
        scp.mirror_status = "NONE"
        scp.mirror_source_id = ""
        scp.mirror_effective_axis = "X"
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


def _clear_native_parent_keep_world(obj):
    if obj is None or getattr(obj, "parent", None) is None:
        return
    mw = obj.matrix_world.copy()
    obj.parent = None
    obj.matrix_world = mw


def _detach_native_scp_parent_links(root, scene):
    for obj in scene.objects:
        if not _is_marked_source_scp(obj, root.name):
            continue
        parent = getattr(obj, "parent", None)
        if parent is None:
            continue
        if not _is_marked_source_scp(parent, root.name):
            continue
        _clear_native_parent_keep_world(obj)


def _has_parent_cycle(start_id, scp_by_id):
    sid = str(start_id or "")
    cur = sid
    seen = set()
    while cur:
        if cur in seen:
            return True
        seen.add(cur)
        scp = scp_by_id.get(cur)
        if scp is None:
            return False
        cur = str(getattr(scp, "parent_id", "") or "")
    return False


def _sync_parent_links(root):
    # Parent link is custom-only in the new SCP model.
    # We only validate parent ids and break invalid/cyclic links.
    scp_by_id = _scp_prop_map(root)
    for scp in root.af_scp_system.scps:
        sid = str(getattr(scp, "id", "") or "")
        pid = str(getattr(scp, "parent_id", "") or "")
        if not pid:
            continue
        if pid == sid or pid not in scp_by_id or _has_parent_cycle(sid, scp_by_id):
            _set_prop_raw(scp, "parent_id", "")
            _set_prop_raw(scp, "attach_initialized", False)


def _normalize_active_index(root):
    idx = int(getattr(root.af_scp_system, "active_scp_index", -1))
    n = len(root.af_scp_system.scps)
    if n <= 0:
        root.af_scp_system.active_scp_index = -1
        return
    if idx < 0 or idx >= n:
        root.af_scp_system.active_scp_index = min(max(idx, 0), n - 1)


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


def _sync_mirrors(sync, root, scene, scp_by_id, target_scp_ids=None):
    mirror_col = sync._get_mirror_collection(scene)

    target_ids = None if target_scp_ids is None else {str(v) for v in set(target_scp_ids)}
    affected_ids = set(target_ids) if target_ids is not None else set()
    desired = set()
    for sid, scp in scp_by_id.items():
        status = str(getattr(scp, "mirror_status", "NONE") or "NONE").upper()
        if status != "TARGET":
            continue

        rule_source_id = str(getattr(scp, "mirror_source_id", "") or "")
        effective_axis = str(getattr(scp, "mirror_effective_axis", "X") or "X").upper()
        src_prop = scp_by_id.get(rule_source_id)

        if target_ids is not None and sid not in target_ids and rule_source_id not in target_ids:
            continue

        affected_ids.add(str(sid))
        if src_prop is None:
            continue

        source_obj = _find_marked_object(scene, root.name, sid)
        if source_obj is None:
            continue

        axis = effective_axis if effective_axis in {"X", "Y", "Z"} else str(getattr(src_prop, "mirror_axis", "X") or "X")
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
        # Keep untouched mirrors when they are not part of current targeted recompute.
        if target_ids is not None and sid not in affected_ids:
            continue
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data and data.users == 0 and isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)


def sync_root_to_scene(
    sync,
    root=None,
    scene=None,
    target_scp_ids=None,
    attachment_parent_source_ids=None,
    attachment_gate_meta=None,
):
    if sync._syncing:
        return

    root, scene = _resolve_sync_inputs(root, scene)
    if root is None:
        return

    sync._syncing = True
    try:
        _discover_marked_scps(root, scene)
        _prune_invalid_scps(root, scene)
        _detach_native_scp_parent_links(root, scene)
        _sync_parent_links(root)
        _normalize_active_index(root)

        scp_by_id = _scp_prop_map(root)
        apply_scp_attachments(
            sync,
            root,
            scene,
            scp_by_id,
            target_scp_ids=target_scp_ids,
            source_parent_ids=attachment_parent_source_ids,
            gate_meta=attachment_gate_meta,
        )
        _sync_mirrors(sync, root, scene, scp_by_id, target_scp_ids=target_scp_ids)
    finally:
        sync._syncing = False


def on_depsgraph_update(sync, scene, depsgraph):
    if sync._syncing:
        return

    root = get_af_root(scene)
    if root is None:
        return

    changed_ids = set()
    transform_ids = set()
    geometry_ids = set()

    for upd in depsgraph.updates:
        obj = upd.id
        if not isinstance(obj, bpy.types.Object):
            continue
        if not _is_marked_source_scp(obj, root.name):
            continue
        is_t = bool(getattr(upd, "is_updated_transform", False))
        is_g = bool(getattr(upd, "is_updated_geometry", False))
        if not is_t and not is_g:
            continue
        sid = str(obj.get("af_scp_id") or "")
        if sid:
            changed_ids.add(sid)
            if is_t:
                transform_ids.add(sid)
            if is_g:
                geometry_ids.add(sid)

    if changed_ids:
        from .sync_runner import sync_from_dirty_hints

        sync_from_dirty_hints(
            root=root,
            scene=scene,
            dirty_hints=dirty_hints_for("SCP", changed_ids),
            source="depsgraph",
            event_type="GEOMETRY" if geometry_ids else "TRANSFORM",
            payload={
                "scp_source_transform_ids": sorted(transform_ids),
                "scp_source_geometry_ids": sorted(geometry_ids),
            },
        )
