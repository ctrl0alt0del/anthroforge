import bpy

from ..deps.dirty_hints import dirty_hints_for
from ..deps.gates import allow_writeback
from ..deps.transform_intents import enqueue_scp_transform_intent
from ..registry import SCPRegistry
from ..utils import get_af_root


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

        _cleanup_stale_root_proxies(sync, vis_col, root.name, all_live_ids)
    finally:
        sync._syncing = False


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
    from .sync_runner import sync_from_dirty_hints

    if changed_ids:
        sync_from_dirty_hints(
            root=root,
            scene=scene,
            dirty_hints=dirty_hints_for("SCP", changed_ids),
            source="depsgraph",
            event_type="SELECTION",
        )


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


def _handle_proxy_transform_update(sync, root, scene, obj, depsgraph, changed_ids, non_source_scp_ids):
    if not obj.get("af_proxy") or obj.get("af_mirror_proxy"):
        return False
    scp_id = str(obj.get("af_scp_id") or "")
    if not scp_id:
        return False
    if not allow_writeback(
        root=root,
        scene=scene,
        source="depsgraph",
        event_type="TRANSFORM",
        entity_type="SCP",
        entity_id=scp_id,
        payload={
            "check_synced_matrix": True,
            "obj": obj,
            "is_synced_matrix_fn": lambda o: bool(sync._is_synced_matrix(o)),
        },
    ):
        return False
    if not enqueue_scp_transform_intent(root, scp_id, obj.matrix_world.copy()):
        return False
    changed_ids.add(scp_id)
    scp_prop = sync._get_scp_prop_by_id(root, scp_id)
    if scp_prop is not None and bool(getattr(scp_prop, "parent_id", "")):
        non_source_scp_ids.add(scp_id)
    return True


def _collect_changed_scp_ids(sync, root, scene, depsgraph, vis_col):
    changed = False
    changed_scp_ids = set()
    non_source_scp_ids = set()
    for update in depsgraph.updates:
        obj = update.id
        if not _is_relevant_proxy_update(root, vis_col, obj):
            continue
        consumed, did = _handle_extension_updates(sync, root, scene, vis_col, obj, depsgraph, changed_scp_ids)
        changed |= did
        if consumed:
            continue
        changed |= _handle_proxy_transform_update(sync, root, scene, obj, depsgraph, changed_scp_ids, non_source_scp_ids)
    return changed, changed_scp_ids, non_source_scp_ids


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
        changed, changed_scp_ids, non_source_scp_ids = _collect_changed_scp_ids(sync, root, scene, depsgraph, vis_col)
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
            payload={"non_source_ids_by_type": {"SCP": set(non_source_scp_ids)}},
        )
