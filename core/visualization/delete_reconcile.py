import bpy
from bpy.app.handlers import persistent

try:
    from ...app.runtime_api import sync_scene
except ImportError:
    from app.runtime_api import sync_scene
from ..deps.dirty_hints import empty_dirty_hints
from ..scp_runtime.bound_objects import sync_all_scp_roles
from ..scp_runtime.prop_update_guard import suppress_scp_prop_updates
from ..utils import get_af_root, scene_for_id
from ..scp_runtime.common import as_id, scp_prop_map, instance_geometry_objects
from ..scp_runtime.marking import normalize_active_index
from ..scp_runtime.tree import sanitize_parent_links
from ..vcp.fiber_modes import fiber_parent_ids
from ..vcp.fiber_node_attachment import clear_fiber_node_attachments
from ..vcp.fiber_node_attachment_codec import node_attachment_target_ids
from ..vcp.prop_update_guard import suppress_vcp_prop_updates
from .fiber_cache_lifecycle import invalidate_fiber_caches

_FIBER_DELETE_CALLBACK = None


def set_fiber_delete_callback(callback):
    global _FIBER_DELETE_CALLBACK
    _FIBER_DELETE_CALLBACK = callback


def _owner_key(obj):
    if obj.get("af_scp_bound") and not obj.get("af_scp_mirror") and obj.get("af_scp_id"):
        return ("SCP", as_id(obj.get("af_scp_id")), _scp_role(obj))
    if obj.get("af_fiber_proxy") and not obj.get("af_fiber_mirror_proxy") and obj.get("af_fiber_id"):
        return ("FIBER", as_id(obj.get("af_fiber_id")), "PROXY")
    if obj.get("af_blob_proxy") and not obj.get("af_blob_mirror_proxy") and obj.get("af_blob_id"):
        return ("BLOB", as_id(obj.get("af_blob_id")), "PROXY")
    if obj.get("af_muscle_proxy") and not obj.get("af_muscle_mirror_proxy") and obj.get("af_muscle_id"):
        return ("MUSCLE", as_id(obj.get("af_muscle_id")), as_id(obj.get("af_muscle_surface")) or "BASE")
    return None


def _scp_role(obj):
    if obj.get("af_scp_transform"):
        return "TRANSFORM"
    if obj.get("af_scp_geometry"):
        return "GEOMETRY"
    return "BOUND"


def _owner_keys(scene, root_name):
    keys = set()
    for obj in scene.objects:
        if obj.get("af_root_name") != root_name:
            continue
        key = _owner_key(obj)
        if key is not None:
            keys.add(key)
    return keys


def _removed_ids(keys, entity_type):
    return {eid for et, eid, _role in set(keys or set()) if et == entity_type}


def _remove_items_by_id(collection, ids):
    indexes = [i for i, item in enumerate(collection) if as_id(getattr(item, "id", "")) in set(ids or set())]
    for index in reversed(indexes):
        collection.remove(index)
    return bool(indexes)


def _clear_active_vcp(root, entity_type, ids):
    vcp = root.af_vcp_system
    valid = str(vcp.active_vcp_type) == str(entity_type)
    valid = valid and as_id(vcp.active_vcp_id) in set(ids or set())
    if not valid:
        return False
    vcp.active_vcp_type, vcp.active_vcp_id = "NONE", ""
    return True


def _remove_muscle_refs(root, fiber_ids):
    changed = False
    for muscle in root.af_vcp_system.muscles:
        indexes = [i for i, ref in enumerate(muscle.fiber_refs) if as_id(ref.fiber_id) in set(fiber_ids or set())]
        for index in reversed(indexes):
            muscle.fiber_refs.remove(index)
            changed = True
    return changed


def _clear_blob_targets(root, target_type, ids):
    changed = False
    for blob in root.af_vcp_system.blobs:
        valid = str(blob.attach_target_type) == str(target_type)
        valid = valid and as_id(blob.attach_target_id) in set(ids or set())
        if not valid:
            continue
        blob.attach_target_type, blob.attach_target_id, blob.attach_target_object_name = "NONE", "", ""
        changed = True
    return changed


def _clear_fiber_muscles(root, muscle_ids):
    changed = False
    for fiber in root.af_vcp_system.fibers:
        if as_id(fiber.muscle_id) not in set(muscle_ids or set()):
            continue
        fiber.muscle_id = ""
        changed = True
    return changed


def _missing_scp_id(scp_id, live_ids):
    sid = as_id(scp_id)
    return bool(sid and sid not in set(live_ids or set()))


def _fiber_orphan_ids(root, live_scp_ids):
    out = set()
    for fiber in root.af_vcp_system.fibers:
        if _missing_fiber_parent(fiber, live_scp_ids):
            out.add(as_id(fiber.id))
    return out


def _missing_fiber_parent(fiber, live_scp_ids):
    from ..vcp.attachment_surface import muscle_backed
    if muscle_backed(fiber): return False
    return any(_missing_scp_id(parent_id, live_scp_ids) for parent_id in fiber_parent_ids(fiber))


def _orphan_blob_scp_ids(root):
    live = set(scp_prop_map(root))
    return {as_id(blob.attach_target_id) for blob in root.af_vcp_system.blobs if str(blob.attach_target_type) == "SCP" and _missing_scp_id(blob.attach_target_id, live)}


def _remove_fibers(root, fiber_ids):
    if _FIBER_DELETE_CALLBACK is not None: _FIBER_DELETE_CALLBACK(root, fiber_ids)
    changed = _remove_items_by_id(root.af_vcp_system.fibers, fiber_ids)
    changed = _clear_active_vcp(root, "FIBER", fiber_ids) or changed
    return _remove_muscle_refs(root, fiber_ids) or changed


def _remove_blobs(root, blob_ids):
    changed = _remove_items_by_id(root.af_vcp_system.blobs, blob_ids)
    return _clear_active_vcp(root, "BLOB", blob_ids) or changed


def _remove_muscles(root, muscle_ids):
    changed = _remove_items_by_id(root.af_vcp_system.muscles, muscle_ids)
    changed = _clear_active_vcp(root, "MUSCLE", muscle_ids) or changed
    changed = _clear_fiber_muscles(root, muscle_ids) or changed
    return _clear_blob_targets(root, "MUSCLE", muscle_ids) or changed


def _reconcile_scp_dependents(root):
    parent_changed, _scp_by_id = sanitize_parent_links(root, scp_prop_map(root))
    live_scp_ids = _live_attachment_ids(root)
    changed = _remove_fibers(root, _fiber_orphan_ids(root, live_scp_ids))
    changed = _clear_orphan_node_attachments(root, live_scp_ids) or changed
    changed = _clear_blob_targets(root, "SCP", _orphan_blob_scp_ids(root)) or changed
    return bool(parent_changed) or changed


def _live_attachment_ids(root):
    scene = scene_for_id(root)
    instances = instance_geometry_objects(scene, root.name) if scene else {}
    return set(scp_prop_map(root)) | set(instances)


def _clear_orphan_node_attachments(root, live_ids):
    changed = False
    for fiber in root.af_vcp_system.fibers:
        from ..vcp.attachment_surface import muscle_backed
        if muscle_backed(fiber): continue
        missing = set(node_attachment_target_ids(fiber)) - set(live_ids or ())
        if missing: clear_fiber_node_attachments(fiber); changed = True
    return changed


def cleanup_scp_dependents(root):
    changed = _reconcile_scp_dependents(root)
    normalize_active_index(root)
    invalidate_fiber_caches(root=root)
    return changed


def reconcile_deleted_entities(root, scene, removed_keys, explicit=False):
    from .warning_runtime import structural_change
    structural_change(root)
    _ = explicit
    with suppress_vcp_prop_updates(), suppress_scp_prop_updates():
        changed = _reconcile_removed(root, removed_keys)
    invalidate_fiber_caches(scene=scene, root=root)
    return changed


def _reconcile_removed(root, removed_keys):
    protected = _protected_removed_fibers(root, removed_keys)
    changed = _remove_muscles(root, _removed_ids(removed_keys, "MUSCLE"))
    changed = _remove_blobs(root, _removed_ids(removed_keys, "BLOB")) or changed
    changed = _remove_fibers(root, _removed_ids(removed_keys, "FIBER") - protected) or changed or bool(protected)
    if _removed_ids(removed_keys, "SCP"):
        changed = _reconcile_scp_objects(root) or changed
    return _reconcile_scp_dependents(root) or changed


def _protected_removed_fibers(root, removed_keys):
    used = {r.fiber_id for s in getattr(root.af_vcp_system, 'fiber_surfaces', ())
            if getattr(s, 'construction_mode', '') == 'BRANCHED_LOFT' for r in s.fiber_refs}
    return used & _removed_ids(removed_keys, 'FIBER')


def _reconcile_scp_objects(root):
    changed = False
    for scp in root.af_scp_system.scps:
        changed = _clear_missing_role_refs(scp) or changed
        changed = _remove_missing_bound_entries(scp) or changed
    sync_all_scp_roles(root)
    normalize_active_index(root)
    return changed


def _clear_missing_role_refs(scp):
    if getattr(scp, "transform_object_ref", None) is None:
        scp.transform_object_ref = None
    if getattr(scp, "geometry_object_ref", None) is None:
        scp.geometry_object_ref = None
    return False


def _remove_missing_bound_entries(scp):
    indexes = [i for i, entry in enumerate(scp.bound_objects) if getattr(entry, "object_ref", None) is None]
    for index in reversed(indexes):
        scp.bound_objects.remove(index)
    return bool(indexes)


class DeleteReconcileRuntime:
    def __init__(self):
        self._owners = {}
        self._objects = {}
        self._syncing = False

    def reset(self):
        self._owners.clear()
        self._objects.clear()

    def on_depsgraph_update(self, scene, depsgraph):
        if not self._syncing:
            self._sync_scene(scene, depsgraph)

    def _sync_scene(self, scene, depsgraph=None):
        root = get_af_root(scene)
        if root is None:
            return
        key = int(scene.session_uid), int(root.session_uid)
        current = self._indexed_owners(scene, root, key, depsgraph)
        previous = self._owners.get(key)
        self._owners[key] = current
        if previous is not None and previous - current:
            self._apply(scene, root, previous - current)

    def _indexed_owners(self, scene, root, key, depsgraph):
        previous = self._objects.get(key, {})
        # Earlier handlers may delete an updated ID; the depsgraph update iterator can then contain freed RNA.
        # Scene membership is authoritative and is already traversed below.
        changed = None
        current = {}
        for obj in scene.objects:
            token = int(obj.session_uid)
            if token in previous and changed is not None and token not in changed: current[token] = previous[token]
            else: current[token] = _owner_key(obj) if obj.get('af_root_name') == root.name else None
        self._objects[key] = current
        return {owner for owner in current.values() if owner is not None}

    def _apply(self, scene, root, removed_keys):
        if reconcile_deleted_entities(root, scene, removed_keys):
            _run_delete_sync(self, scene, root)


def _run_delete_sync(runtime, scene, root):
    runtime._syncing = True
    try:
        sync_scene(root=root, scene=scene, dirty_hints=empty_dirty_hints(), source="depsgraph", event_type="DELETE")
    finally:
        runtime._syncing = False


_DELETE_RECONCILE = None


@persistent
def _on_load_post(_dummy):
    if _DELETE_RECONCILE is not None:
        _DELETE_RECONCILE.reset()


def register_delete_reconcile():
    global _DELETE_RECONCILE
    if _DELETE_RECONCILE is None:
        _DELETE_RECONCILE = DeleteReconcileRuntime()
    if _DELETE_RECONCILE.on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_DELETE_RECONCILE.on_depsgraph_update)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    for group in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if _on_load_post not in group: group.append(_on_load_post)
    return _DELETE_RECONCILE


def unregister_delete_reconcile():
    global _DELETE_RECONCILE
    if _DELETE_RECONCILE is None:
        return
    if _DELETE_RECONCILE.on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_DELETE_RECONCILE.on_depsgraph_update)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    for group in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if _on_load_post in group: group.remove(_on_load_post)
    _DELETE_RECONCILE = None
