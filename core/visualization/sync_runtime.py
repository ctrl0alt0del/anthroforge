import bpy
from mathutils import Vector

from ..attachment_codec import parse_scp_attach_param, encode_surface_frame
from ..registry import SCPRegistry
from ..utils import get_af_root


def sync_root_to_scene(sync, root=None, scene=None, target_scp_ids=None):
    if sync._syncing:
        return

    scene = scene or bpy.context.scene
    root = root or get_af_root(scene)
    if root is None or scene is None:
        return

    sync._syncing = True
    try:
        vis_col = sync._get_vis_collection(scene)

        runtime = SCPRegistry(root)
        runtime.build()

        all_live_ids = set(runtime.registry.keys())
        if target_scp_ids is None:
            ids_to_sync = all_live_ids
        else:
            ids_to_sync = set(target_scp_ids) & all_live_ids

        for scp_id in ids_to_sync:
            scp = runtime.registry.get(scp_id)
            if scp is None:
                continue

            obj = sync._find_proxy(vis_col, root.name, scp_id)
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

        for ext in sync._shape_sync_extensions:
            ext.sync_post(sync, root, scene, vis_col)

        if target_scp_ids is None:
            for obj in list(sync._iter_root_proxies(vis_col, root.name)):
                if obj.get("af_scp_id") not in all_live_ids:
                    sync._remove_proxy(obj)
    finally:
        sync._syncing = False


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
        if not sync._is_user_translate_active():
            return False, None

        parent = runtime.registry.get(scp_prop.parent_id)
        child = runtime.registry.get(scp_id)
        if parent is None or child is None:
            return False, None

        parent_proxy = sync._find_proxy_in_scene(scene, root.name, scp_prop.parent_id)
        if parent_proxy is None:
            return False, None

        child_world_loc = proxy_obj.matrix_world.to_translation()
        parent_param = sync._nearest_parent_param(parent, parent_proxy, child_world_loc)
        parent_local_point, _pt, _pn = parent.shape.sample_attachment_frame_local(parent_param)
        anchor_world = parent_proxy.matrix_world @ parent_local_point

        child_origin_local = sync._nearest_mesh_point_local(proxy_obj, anchor_world, depsgraph)
        if child_origin_local is None:
            child_origin_local = Vector((0.0, 0.0, 0.0))

        mode, payload = parse_scp_attach_param(scp_prop.attach_param)
        if mode == "surface_frame_v1":
            child_tangent_local = payload.get("child_tangent_local", Vector((1.0, 0.0, 0.0)))
            child_normal_local = payload.get("child_normal_local", Vector((0.0, 0.0, 1.0)))
        else:
            child_tangent_local = Vector((1.0, 0.0, 0.0))
            child_normal_local = Vector((0.0, 0.0, 1.0))

        scp_prop.attach_param = encode_surface_frame(
            parent_param=parent_param,
            child_origin_local=child_origin_local,
            child_tangent_local=child_tangent_local,
            child_normal_local=child_normal_local,
        )
        scp_prop.local_origin = (0.0, 0.0, 0.0)
        return True, scp_id

    local_matrix = proxy_obj.matrix_world
    loc, rot, scale = local_matrix.decompose()
    scp_prop.local_origin = (loc.x, loc.y, loc.z)
    scp_prop.local_rotation = (rot.w, rot.x, rot.y, rot.z)
    scp_prop.local_scale = (scale.x, scale.y, scale.z)
    return True, scp_id


def on_depsgraph_update(sync, scene, depsgraph):
    if sync._syncing:
        return

    root = get_af_root(scene)
    if root is None:
        return

    active_scp_id = sync._active_scp_id_from_context(root)
    if active_scp_id != sync._last_active_scp_id:
        changed_ids = set()
        if sync._last_active_scp_id:
            changed_ids.add(sync._last_active_scp_id)
        if active_scp_id:
            changed_ids.add(active_scp_id)
        sync._last_active_scp_id = active_scp_id
        sync.sync_root_to_scene(root=root, scene=scene, target_scp_ids=changed_ids or None)

    vis_col = bpy.data.collections.get(sync.collection_name)
    if vis_col is None:
        return

    changed = False
    changed_scp_ids = set()

    sync._syncing = True
    try:
        for update in depsgraph.updates:
            obj = update.id
            if not isinstance(obj, bpy.types.Object):
                continue
            if obj.get("af_root_name") != root.name:
                continue
            if vis_col.objects.get(obj.name) is None:
                continue

            consumed = False
            for ext in sync._shape_sync_extensions:
                ext_consumed, did, sid = ext.handle_object_update(sync, root, scene, vis_col, obj, depsgraph)
                if not ext_consumed:
                    continue
                consumed = True
                changed |= did
                if sid:
                    changed_scp_ids.add(sid)
                break
            if consumed:
                continue

            if not obj.get("af_proxy"):
                continue
            if obj.get("af_mirror_proxy"):
                continue
            if sync._is_synced_matrix(obj):
                continue

            did, sid = sync._write_proxy_transform_to_data(root, obj, scene, depsgraph)
            changed |= did
            if sid:
                changed_scp_ids.add(sid)
    finally:
        sync._syncing = False

    if changed and changed_scp_ids:
        from .sync_runner import sync_from_scp_ids

        sync_from_scp_ids(root=root, scene=scene, scp_ids=changed_scp_ids)
