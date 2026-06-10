from ..queries.root import root_for_context
from .results import failure, success


def mark_active_mesh_as_scp(context):
    root = root_for_context(context)
    obj, error = _mark_target(root, context)
    if obj is None:
        return failure(error)
    scp = _create_marked_scp(root, context, obj)
    ok, error = _apply_optional_parent(context, root, scp)
    if not ok:
        return failure(error)
    _finalize_mark(context, root, scp, obj)
    return success(f"Marked '{obj.name}' as {scp.id}", value=scp)


def set_active_scp_parent(context):
    root = root_for_context(context)
    child, error = _resolved_active_child(root, context)
    if child is None:
        return failure(error)
    parent_obj = getattr(context.scene, "af_scp_parent_obj", None)
    return _apply_parent_result(context, root, child, parent_obj)


def reparent_scp(context, child_scp_id, parent_scp_id=""):
    root = root_for_context(context)
    child, error = _resolved_child_by_id(root, context.scene, child_scp_id)
    if child is None:
        return failure(error)
    parent_obj, error = _resolved_parent_by_id(root, context.scene, parent_scp_id)
    if error:
        return failure(error)
    return _apply_parent_result(context, root, child, parent_obj)


def _mark_target(root, context):
    obj = getattr(context, "active_object", None)
    if root is None:
        return None, "No AF_ROOT found in scene."
    if obj is None or getattr(obj, "type", None) != "MESH":
        return None, "Select a mesh object first."
    if obj.get("af_scp_mirror"):
        return None, "Cannot mark mirror object as SCP."
    if _scp_for_object()(root, obj) is not None:
        return None, "Object already belongs to an SCP."
    return obj, ""


def _create_marked_scp(root, context, obj):
    scp = _create_scp()(root, obj.name)
    _set_transform_object()(root, scp, obj)
    _set_geometry_object()(root, scp, obj)
    _enable_object_color_view()(context)
    return scp


def _apply_optional_parent(context, root, scp):
    child_obj = getattr(scp, "transform_object_ref", None)
    parent_obj = _optional_parent_obj(context.scene, root)
    if parent_obj is None:
        _set_parent_relation()(child_obj, scp, None)
        return True, ""
    return _apply_parent_change(context, root, child_obj, scp, parent_obj)


def _optional_parent_obj(scene, root):
    obj = getattr(scene, "af_scp_parent_obj", None)
    return obj if _is_transform_scp_obj()(obj, root.name) else None


def _finalize_mark(context, root, scp, obj):
    _activate_scp()(root, scp.id)
    _select_only(context, obj)
    _sync_entity(context, scp.id, "MARK")
    _notify_selection_changed()(context.scene, force=True, active_object=obj)


def _select_only(context, obj):
    for other in getattr(context, "selected_objects", ()):
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _resolved_active_child(root, context):
    scp = None if root is None else _active_scp_from_context()(root, context)
    obj = None if scp is None else _find_transform_obj()(context.scene, root.name, scp.id)
    return ((obj, scp), "") if obj is not None else (None, "Active object must belong to an SCP.")


def _resolved_child_by_id(root, scene, scp_id):
    scp = None if root is None else _find_scp_by_id()(root, scp_id)
    obj = None if scp is None else _find_transform_obj()(scene, root.name, scp.id)
    return ((obj, scp), "") if obj is not None else (None, "Target SCP not found.")


def _resolved_parent_by_id(root, scene, parent_scp_id):
    pid = str(parent_scp_id or "")
    if not pid:
        return None, ""
    obj = None if root is None else _find_transform_obj()(scene, root.name, pid)
    return (obj, "") if obj is not None else (None, "Target parent SCP has no transform object.")


def _apply_parent_result(context, root, child, parent_obj):
    child_obj, child_scp = child
    ok, error = _apply_parent_change(context, root, child_obj, child_scp, parent_obj)
    if not ok:
        return failure(error)
    _sync_entity(context, child_scp.id)
    return success(value=child_scp)


def _apply_parent_change(context, root, child_obj, child_scp, parent_obj):
    error = _parent_error(root, child_scp.id, parent_obj)
    if error:
        return False, error
    if parent_obj is None:
        _set_parent_relation()(child_obj, child_scp, None)
        return True, ""
    return _capture_parent_change(context, root.name, child_obj, child_scp, parent_obj)


def _parent_error(root, child_id, parent_obj):
    if parent_obj is None:
        return ""
    if not _is_transform_scp_obj()(parent_obj, root.name):
        return "Parent must be another SCP transform object."
    if _would_create_parent_cycle()(root, child_id, parent_obj.get("af_scp_id")):
        return "Parent relation would create a cycle."
    return ""


def _capture_parent_change(context, root_name, child_obj, child_scp, parent_obj):
    snapshot = _snapshot_link_state()(child_scp)
    child_geo, parent_geo = _attachment_geometry(context.scene, root_name, child_scp, parent_obj)
    _maybe_force_object_origin(child_scp, child_geo)
    _set_parent_relation()(child_obj, child_scp, parent_obj)
    if _capture_attachment()(child_scp, child_obj, child_geo, parent_obj, parent_geo):
        return True, ""
    _restore_link_state()(child_scp, snapshot)
    return False, "Failed to capture attachment."


def _attachment_geometry(scene, root_name, child_scp, parent_obj):
    finder = _find_geometry_obj()
    parent_id = parent_obj.get("af_scp_id")
    return finder(scene, root_name, child_scp.id), finder(scene, root_name, parent_id)


def _maybe_force_object_origin(child_scp, child_geo):
    mode = getattr(child_scp, "attach_child_anchor_mode", "FACE_CENTER")
    if child_geo is None and mode != "OBJECT_ORIGIN":
        _set_prop_raw()(child_scp, "attach_child_anchor_mode", "OBJECT_ORIGIN")


def _sync_entity(context, scp_id, event_type="UPDATE"):
    _sync_context()(context, dirty_hints=_dirty_hints_for()("SCP", {scp_id}), source="operator", event_type=event_type)


def _sync_context():
    try:
        from ...app.runtime_api import sync_context
    except ImportError:
        from app.runtime_api import sync_context
    return sync_context


def _dirty_hints_for():
    try:
        from ...core.deps.dirty_hints import dirty_hints_for
    except ImportError:
        from core.deps.dirty_hints import dirty_hints_for
    return dirty_hints_for


def _create_scp():
    try:
        from ...core.scp_runtime.object_roles import create_scp
    except ImportError:
        from core.scp_runtime.object_roles import create_scp
    return create_scp


def _active_scp_from_context():
    try:
        from ...core.scp_runtime.object_roles import active_scp_from_context
    except ImportError:
        from core.scp_runtime.object_roles import active_scp_from_context
    return active_scp_from_context


def _set_transform_object():
    try:
        from ...core.scp_runtime.object_roles import set_scp_transform_object
    except ImportError:
        from core.scp_runtime.object_roles import set_scp_transform_object
    return set_scp_transform_object


def _set_geometry_object():
    try:
        from ...core.scp_runtime.object_roles import set_scp_geometry_object
    except ImportError:
        from core.scp_runtime.object_roles import set_scp_geometry_object
    return set_scp_geometry_object


def _enable_object_color_view():
    try:
        from ...core.scp_runtime.object_colors import enable_object_color_view
    except ImportError:
        from core.scp_runtime.object_colors import enable_object_color_view
    return enable_object_color_view


def _activate_scp():
    try:
        from ...core.scp_runtime.lookup import activate_scp
    except ImportError:
        from core.scp_runtime.lookup import activate_scp
    return activate_scp


def _set_parent_relation():
    try:
        from ...core.scp_runtime.lookup import set_parent_relation
    except ImportError:
        from core.scp_runtime.lookup import set_parent_relation
    return set_parent_relation


def _would_create_parent_cycle():
    try:
        from ...core.scp_runtime.lookup import would_create_parent_cycle
    except ImportError:
        from core.scp_runtime.lookup import would_create_parent_cycle
    return would_create_parent_cycle


def _find_scp_by_id():
    try:
        from ...core.scp_runtime.common import find_scp_by_id
    except ImportError:
        from core.scp_runtime.common import find_scp_by_id
    return find_scp_by_id


def _find_transform_obj():
    try:
        from ...core.scp_runtime.common import find_transform_scp_obj
    except ImportError:
        from core.scp_runtime.common import find_transform_scp_obj
    return find_transform_scp_obj


def _find_geometry_obj():
    try:
        from ...core.scp_runtime.common import find_geometry_mesh_scp_obj
    except ImportError:
        from core.scp_runtime.common import find_geometry_mesh_scp_obj
    return find_geometry_mesh_scp_obj


def _is_transform_scp_obj():
    try:
        from ...core.scp_runtime.common import is_transform_scp_obj
    except ImportError:
        from core.scp_runtime.common import is_transform_scp_obj
    return is_transform_scp_obj


def _scp_for_object():
    try:
        from ...core.scp_runtime.common import scp_for_object
    except ImportError:
        from core.scp_runtime.common import scp_for_object
    return scp_for_object


def _set_prop_raw():
    try:
        from ...core.scp_runtime.common import set_prop_raw
    except ImportError:
        from core.scp_runtime.common import set_prop_raw
    return set_prop_raw


def _snapshot_link_state():
    try:
        from ...core.scp_runtime.link_state import snapshot_link_state
    except ImportError:
        from core.scp_runtime.link_state import snapshot_link_state
    return snapshot_link_state


def _restore_link_state():
    try:
        from ...core.scp_runtime.link_state import restore_link_state
    except ImportError:
        from core.scp_runtime.link_state import restore_link_state
    return restore_link_state


def _capture_attachment():
    try:
        from ...core.scp_runtime.attachment_runtime import capture_attachment_from_link
    except ImportError:
        from core.scp_runtime.attachment_runtime import capture_attachment_from_link
    return capture_attachment_from_link


def _notify_selection_changed():
    try:
        from ...core.visualization.control_runtime import notify_selection_changed
    except ImportError:
        from core.visualization.control_runtime import notify_selection_changed
    return notify_selection_changed
