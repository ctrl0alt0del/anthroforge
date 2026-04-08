import bpy
from mathutils import Matrix, Vector

from ..attachment_codec import parse_scp_attach_param, encode_surface_frame, encode_scp_mesh_anchor
from ..deps.dirty_hints import dirty_hints_for
from ..deps.gates import allow_writeback
from ..registry import SCPRegistry
from ..utils import get_af_root
from .scp_sync_helpers import frame_basis3


def _resolve_sync_inputs(root, scene):
    scene = scene or bpy.context.scene
    root = root or get_af_root(scene)
    if root is None or scene is None:
        return None, None
    return root, scene


def _ids_to_sync(runtime_registry, target_scp_ids):
    all_live_ids = set(runtime_registry.keys())
    if target_scp_ids is None:
        return all_live_ids, all_live_ids
    return all_live_ids, set(target_scp_ids) & all_live_ids


def _sync_single_proxy(sync, vis_col, root, scene, runtime, scp):
    obj = sync._find_proxy(vis_col, root.name, scp.id)
    if obj is None:
        obj = sync._create_proxy(vis_col, root, scp)
    elif not sync._object_matches_shape(obj, scp):
        sync._replace_proxy_data(obj, scp)
    obj["af_proxy"] = True
    obj["af_root_name"] = root.name
    obj["af_scp_id"] = scp.id
    if obj.parent != root:
        obj.parent = root
        obj.matrix_parent_inverse = root.matrix_world.inverted()
    scp.shape.ensure_proxy_object(obj)
    obj.matrix_world = sync._compute_visual_world_matrix(scp, runtime.registry, root, scene)
    sync._mark_synced_matrix(obj)


def _cleanup_stale_root_proxies(sync, vis_col, root_name, live_ids):
    for obj in list(sync._iter_root_proxies(vis_col, root_name)):
        if obj.get("af_scp_id") not in live_ids:
            sync._remove_proxy(obj)


def sync_root_to_scene(sync, root=None, scene=None, target_scp_ids=None):
    if sync._syncing:
        return

    root, scene = _resolve_sync_inputs(root, scene)
    if root is None:
        return

    sync._syncing = True
    try:
        vis_col = sync._get_vis_collection(scene)

        runtime = SCPRegistry(root)
        runtime.build()

        all_live_ids, ids_to_sync = _ids_to_sync(runtime.registry, target_scp_ids)

        for scp_id in ids_to_sync:
            scp = runtime.registry.get(scp_id)
            if scp is None:
                continue
            _sync_single_proxy(sync, vis_col, root, scene, runtime, scp)

        for ext in sync._shape_sync_extensions:
            ext.sync_post(sync, root, scene, vis_col)

        if target_scp_ids is None:
            _cleanup_stale_root_proxies(sync, vis_col, root.name, all_live_ids)
    finally:
        sync._syncing = False


def _get_child_surface_frame(payload):
    tangent = payload.get("child_tangent_local", Vector((1.0, 0.0, 0.0)))
    normal = payload.get("child_normal_local", Vector((0.0, 0.0, 1.0)))
    return tangent, normal


def _write_parented_transform(sync, root, runtime, scp_prop, proxy_obj, scene, depsgraph):
    if not allow_writeback(
        root=root,
        scene=scene,
        source="depsgraph",
        event_type="TRANSFORM",
        entity_type="SCP",
        entity_id=scp_prop.id,
        payload={
            "require_user_transform": "TRANSLATE",
            "is_user_transform_active": lambda _req: bool(sync._is_user_translate_active()),
        },
    ):
        return False, None
    parent = runtime.registry.get(scp_prop.parent_id)
    child = runtime.registry.get(scp_prop.id)
    parent_proxy = sync._find_proxy_in_scene(scene, proxy_obj.get("af_root_name"), scp_prop.parent_id)
    if parent is None or child is None or parent_proxy is None:
        return False, None
    mode, payload = parse_scp_attach_param(scp_prop.attach_param)
    obj_origin = proxy_obj.matrix_world.to_translation()
    parent_param = sync._nearest_parent_param(parent, parent_proxy, obj_origin)

    if mode == "mesh_anchor":
        parent_local_point = parent.shape.compute_local_point(parent_param)
        anchor_world = parent_proxy.matrix_world @ parent_local_point
        rs = child.local_rotation.to_4x4() @ Matrix.Diagonal((*child.local_scale, 1.0))
        off4 = rs.inverted_safe() @ Vector((anchor_world.x - obj_origin.x, anchor_world.y - obj_origin.y, anchor_world.z - obj_origin.z, 1.0))
        child_local_point = Vector((off4.x, off4.y, off4.z))
        scp_prop.attach_param = encode_scp_mesh_anchor(parent_local_point, child_local_point)
    else:
        child_tangent_local, child_normal_local = _get_child_surface_frame(payload)

        p_origin_local, p_tangent_local, p_normal_local = parent.shape.sample_attachment_frame_local(parent_param)
        mw = parent_proxy.matrix_world
        mw3 = mw.to_3x3()
        p_origin_world = mw @ p_origin_local
        p_tangent_world = mw3 @ p_tangent_local
        p_normal_world = mw3 @ p_normal_local

        parent_basis = frame_basis3(p_tangent_world, p_normal_world)
        child_basis_local = frame_basis3(child_tangent_local, child_normal_local)
        attach_rot = parent_basis @ child_basis_local.inverted()
        final_rot = attach_rot @ child.local_rotation

        off_world = p_origin_world - obj_origin
        off_local_scaled = final_rot.inverted() @ off_world

        sx = max(1e-9, float(child.local_scale.x))
        sy = max(1e-9, float(child.local_scale.y))
        sz = max(1e-9, float(child.local_scale.z))
        child_origin_local = Vector((off_local_scaled.x / sx, off_local_scaled.y / sy, off_local_scaled.z / sz))

        scp_prop.attach_param = encode_surface_frame(
            parent_param=parent_param,
            child_origin_local=child_origin_local,
            child_tangent_local=child_tangent_local,
            child_normal_local=child_normal_local,
        )

    scp_prop.local_origin = (0.0, 0.0, 0.0)
    return True, scp_prop.id


def _write_root_transform(scp_prop, proxy_obj):
    loc, rot, scale = proxy_obj.matrix_world.decompose()
    scp_prop.local_origin = (loc.x, loc.y, loc.z)
    scp_prop.local_rotation = (rot.w, rot.x, rot.y, rot.z)
    scp_prop.local_scale = (scale.x, scale.y, scale.z)
    return True, scp_prop.id


def write_proxy_transform_to_data(sync, root, proxy_obj, scene, depsgraph):
    scp_id = proxy_obj.get("af_scp_id")
    if not scp_id:
        return False, None

    scp_prop = sync._get_scp_prop_by_id(root, scp_id)
    if scp_prop is None:
        return False, None

    runtime = SCPRegistry(root)
    runtime.build()

    if scp_prop.parent_id:
        return _write_parented_transform(sync, root, runtime, scp_prop, proxy_obj, scene, depsgraph)
    return _write_root_transform(scp_prop, proxy_obj)


def _handle_active_switch(sync, root, scene):
    active_scp_id = sync._active_scp_id_from_context(root)
    if active_scp_id == sync._last_active_scp_id:
        return
    changed_ids = set()
    if sync._last_active_scp_id:
        changed_ids.add(sync._last_active_scp_id)
    if active_scp_id:
        changed_ids.add(active_scp_id)
    sync._last_active_scp_id = active_scp_id
    # Route active selection refresh through dependency runtime.
    from .sync_runner import sync_all, sync_from_dirty_hints

    if changed_ids:
        sync_from_dirty_hints(
            root=root,
            scene=scene,
            dirty_hints=dirty_hints_for("SCP", changed_ids),
            source="depsgraph",
            event_type="SELECTION",
        )
    else:
        sync_all(root=root, scene=scene, bake=False, source="depsgraph", event_type="SELECTION")


def _is_relevant_proxy_update(root, vis_col, obj):
    if not isinstance(obj, bpy.types.Object):
        return False
    if obj.get("af_root_name") != root.name:
        return False
    return vis_col.objects.get(obj.name) is not None


def _handle_extension_updates(sync, root, scene, vis_col, obj, depsgraph, changed_ids):
    for ext in sync._shape_sync_extensions:
        consumed, did, sid = ext.handle_object_update(sync, root, scene, vis_col, obj, depsgraph)
        if not consumed:
            continue
        if did and sid:
            changed_ids.add(sid)
        return consumed, bool(did)
    return False, False


def _handle_proxy_transform_update(sync, root, scene, obj, depsgraph, changed_ids):
    if not obj.get("af_proxy") or obj.get("af_mirror_proxy"):
        return False
    if not allow_writeback(
        root=root,
        scene=scene,
        source="depsgraph",
        event_type="TRANSFORM",
        entity_type="SCP",
        entity_id=str(obj.get("af_scp_id") or ""),
        payload={
            "check_synced_matrix": True,
            "obj": obj,
            "is_synced_matrix_fn": lambda o: bool(sync._is_synced_matrix(o)),
        },
    ):
        return False
    did, sid = sync._write_proxy_transform_to_data(root, obj, scene, depsgraph)
    if did and sid:
        changed_ids.add(sid)
    return bool(did)


def _collect_changed_scp_ids(sync, root, scene, depsgraph, vis_col):
    changed = False
    changed_scp_ids = set()
    for update in depsgraph.updates:
        obj = update.id
        if not _is_relevant_proxy_update(root, vis_col, obj):
            continue
        consumed, did = _handle_extension_updates(sync, root, scene, vis_col, obj, depsgraph, changed_scp_ids)
        changed |= did
        if consumed:
            continue
        changed |= _handle_proxy_transform_update(sync, root, scene, obj, depsgraph, changed_scp_ids)
    return changed, changed_scp_ids


def on_depsgraph_update(sync, scene, depsgraph):
    if sync._syncing:
        return

    root = get_af_root(scene)
    if root is None:
        return

    _handle_active_switch(sync, root, scene)

    vis_col = bpy.data.collections.get(sync.collection_name)
    if vis_col is None:
        return

    sync._syncing = True
    try:
        changed, changed_scp_ids = _collect_changed_scp_ids(sync, root, scene, depsgraph, vis_col)
    finally:
        sync._syncing = False

    if changed and changed_scp_ids:
        from .sync_runner import sync_from_dirty_hints

        sync_from_dirty_hints(
            root=root,
            scene=scene,
            dirty_hints=dirty_hints_for("SCP", changed_scp_ids),
            source="depsgraph",
            event_type="TRANSFORM",
        )
