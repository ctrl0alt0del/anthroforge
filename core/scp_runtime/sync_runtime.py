import bpy

from ..deps.dirty_hints import dirty_hints_for
from ..utils import get_af_root
from .attachment_runtime import apply_scp_attachments
from .bound_objects import sync_all_scp_roles
from .common import as_id, is_bound_scp_obj, payload_id_set, scp_prop_map
from .marking import detach_native_scp_parent_links, normalize_active_index, sync_parent_links
from .mirror_scene import sync_mirrors


def _resolve_sync_inputs(root, scene):
    scene = scene or bpy.context.scene
    root = root or get_af_root(scene)
    return (None, None) if root is None or scene is None else (root, scene)


def sync_root_to_scene(sync, root=None, scene=None, target_scp_ids=None, attachment_parent_ids=None, attachment_gate_meta=None):
    if sync._syncing:
        return
    root, scene = _resolve_sync_inputs(root, scene)
    if root is None:
        return
    _run_sync_pass(sync, root, scene, target_scp_ids, attachment_parent_ids, attachment_gate_meta)


def _refresh_view_layer():
    try:
        bpy.context.view_layer.update()
    except Exception:
        return


def _run_sync_pass(sync, root, scene, target_scp_ids, attachment_parent_ids, attachment_gate_meta):
    sync._syncing = True
    try:
        sync_all_scp_roles(root)
        detach_native_scp_parent_links(root, scene)
        sync_parent_links(root)
        normalize_active_index(root)
        scp_by_id = scp_prop_map(root)
        _refresh_view_layer()
        apply_scp_attachments(sync, root, scene, scp_by_id, target_scp_ids, attachment_parent_ids, attachment_gate_meta)
        _refresh_view_layer()
        sync_mirrors(sync, root, scene, scp_by_id, target_scp_ids=target_scp_ids)
    finally:
        sync._syncing = False


def on_depsgraph_update(sync, scene, depsgraph):
    if sync._syncing:
        return
    root = get_af_root(scene)
    if root is None:
        return
    _sync_from_depsgraph(sync, root, scene, depsgraph)


def _sync_from_depsgraph(sync, root, scene, depsgraph):
    changed_ids, transform_ids, geometry_ids = _depsgraph_change_sets(root, depsgraph)
    if not changed_ids:
        return
    from ..visualization.sync_runner import sync_from_dirty_hints
    sync_from_dirty_hints(root=root, scene=scene, dirty_hints=dirty_hints_for("SCP", changed_ids), source="depsgraph", event_type="SCP_UPDATE", payload=_payload(transform_ids, geometry_ids))


def _depsgraph_change_sets(root, depsgraph):
    changed_ids, transform_ids, geometry_ids = set(), set(), set()
    for update in depsgraph.updates:
        _collect_update(root, update, changed_ids, transform_ids, geometry_ids)
    return changed_ids, transform_ids, geometry_ids


def _collect_update(root, update, changed_ids, transform_ids, geometry_ids):
    obj = update.id
    if not isinstance(obj, bpy.types.Object) or not is_bound_scp_obj(obj, root.name):
        return
    is_transform = bool(getattr(update, "is_updated_transform", False))
    is_geometry = bool(getattr(update, "is_updated_geometry", False))
    if not _has_role_update(obj, is_transform, is_geometry):
        return
    _record_update_ids(obj, changed_ids, transform_ids if _transform_role_changed(obj, is_transform) else None, geometry_ids if _geometry_role_changed(obj, is_transform, is_geometry) else None)


def _has_role_update(obj, is_transform, is_geometry):
    return _transform_role_changed(obj, is_transform) or _geometry_role_changed(obj, is_transform, is_geometry)


def _transform_role_changed(obj, is_transform):
    return bool(is_transform and obj.get("af_scp_transform"))


def _geometry_role_changed(obj, is_transform, is_geometry):
    return bool(obj.get("af_scp_geometry") and (is_transform or is_geometry))


def _record_update_ids(obj, changed_ids, transform_ids, geometry_ids):
    sid = as_id(obj.get("af_scp_id"))
    if not sid:
        return
    changed_ids.add(sid)
    if transform_ids is not None:
        transform_ids.add(sid)
    if geometry_ids is not None:
        geometry_ids.add(sid)


def _payload(transform_ids, geometry_ids):
    apply_ids = set(geometry_ids or set()) | set(transform_ids or set())
    return {"scp_recapture_ids": sorted(transform_ids), "scp_apply_parent_ids": sorted(apply_ids)}
