import os

import bpy

from ..deps.runtime_trace import trace_line
from ..deps.dirty_hints import dirty_hints_for
from ..perf_trace import perf_time, perf_timer
from ..shortcuts.session_state import consume_suppressed_ids
from ..utils import get_af_root, scene_for_id, update_scene_view_layer
from .attachment_runtime import apply_scp_attachments
from .bound_objects import sync_all_scp_roles, sync_scp_roles_for_ids
from .common import as_id, is_bound_scp_obj, scp_prop_map
from .marking import detach_native_scp_parent_links, normalize_active_index, sync_parent_links
from .mirror_scene import sync_mirrors
from .tree import children_map


def _resolve_sync_inputs(root, scene):
    scene = scene or scene_for_id(root)
    root = root or get_af_root(scene)
    return (None, None) if root is None or scene is None else (root, scene)


def sync_root_to_scene(sync, root=None, scene=None, target_scp_ids=None,
                       attachment_parent_ids=None, attachment_gate_meta=None,
                       attachment_fiber_ids=None):
    if sync._syncing:
        return
    root, scene = _resolve_sync_inputs(root, scene)
    if root is None:
        return
    return _run_sync_pass(sync, root, scene, target_scp_ids, attachment_parent_ids,
                          attachment_gate_meta, attachment_fiber_ids)


def _refresh_view_layer(scene):
    update_scene_view_layer(scene)


def _trace_flag(name):
    raw = str(os.environ.get(name, "") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _sync_trace(text):
    trace_line(text) if _trace_flag("AF_DEPS_TRACE") or _trace_flag("AF_MIRROR_TRACE") else None


def _sorted_ids(values):
    return sorted(set(values or set()))


def _trace_sync_start(target_scp_ids, attachment_parent_ids):
    _sync_trace(f"sync start targets={_sorted_ids(target_scp_ids)} parents={_sorted_ids(attachment_parent_ids)}")


def _sync_pass_body(sync, root, scene, target_scp_ids, attachment_parent_ids,
                    attachment_gate_meta, attachment_fiber_ids):
    start = perf_timer()
    try:
        return _sync_pass_steps(sync, root, scene, target_scp_ids, attachment_parent_ids,
                                attachment_gate_meta, attachment_fiber_ids)
    finally:
        perf_time(scene, "scp_sync_body", start)


def _sync_pass_steps(sync, root, scene, target_scp_ids, attachment_parent_ids,
                     attachment_gate_meta, attachment_fiber_ids):
    _sync_roles(root, target_scp_ids, attachment_parent_ids)
    detach_native_scp_parent_links(root, scene)
    sync_parent_links(root)
    normalize_active_index(root)
    scp_by_id = scp_prop_map(root)
    report = apply_scp_attachments(sync, root, scene, scp_by_id, target_scp_ids,
        attachment_parent_ids, attachment_gate_meta, attachment_fiber_ids)
    sync_mirrors(sync, root, scene, scp_by_id, target_scp_ids=target_scp_ids)
    _refresh_view_layer(scene)
    return report


def _sync_roles(root, target_scp_ids, attachment_parent_ids):
    ids = _role_scope_ids(root, target_scp_ids, attachment_parent_ids)
    sync_all_scp_roles(root) if ids is None else sync_scp_roles_for_ids(root, ids)


def _role_scope_ids(root, target_scp_ids, attachment_parent_ids):
    if target_scp_ids is None:
        return None
    seeds = {as_id(v) for v in set(target_scp_ids or set()) | set(attachment_parent_ids or set()) if as_id(v)}
    return _expanded_role_ids({as_id(s.id): s for s in root.af_scp_system.scps}, seeds)


def _expanded_role_ids(scp_by_id, seeds):
    kids, out, stack = children_map(scp_by_id), set(seeds or set()), list(seeds or set())
    while stack:
        current = stack.pop()
        for child_id in kids.get(current, ()):
            if child_id not in out:
                out.add(child_id); stack.append(child_id)
    return out


def _run_sync_pass(sync, root, scene, target_scp_ids, attachment_parent_ids,
                   attachment_gate_meta, attachment_fiber_ids):
    sync._syncing = True
    _trace_sync_start(target_scp_ids, attachment_parent_ids)
    try:
        result = _sync_pass_body(sync, root, scene, target_scp_ids, attachment_parent_ids,
                                 attachment_gate_meta, attachment_fiber_ids)
        _sync_trace("sync end")
        return result
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
    changed_ids, transform_ids, geometry_ids = _filtered_changes(changed_ids, transform_ids, geometry_ids)
    if not changed_ids:
        return
    _sync_trace(f"depsgraph changed={_sorted_ids(changed_ids)} transform={_sorted_ids(transform_ids)} geometry={_sorted_ids(geometry_ids)}")
    from ..visualization.sync_runner import schedule_sync_from_dirty_hints
    schedule_sync_from_dirty_hints(root=root, scene=scene, dirty_hints=dirty_hints_for("SCP", changed_ids), source="depsgraph", event_type="SCP_UPDATE", payload=_payload(transform_ids, geometry_ids))


def _filtered_changes(changed_ids, transform_ids, geometry_ids):
    keep = consume_suppressed_ids(changed_ids)
    return keep, set(transform_ids or set()) & keep, set(geometry_ids or set()) & keep


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
    t_ids = transform_ids if _transform_role_changed(obj, is_transform) else None
    g_ids = geometry_ids if _geometry_role_changed(obj, is_transform, is_geometry) else None
    _record_update_ids(obj, changed_ids, t_ids, g_ids)


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
    return {"scp_recapture_ids": sorted(transform_ids), "scp_apply_parent_ids": sorted(apply_ids), "scp_apply_target_ids": sorted(apply_ids)}
