from ..deps.dirty_hints import dirty_hints_for
from ..utils import get_af_root
from ..visualization.sync_runner import sync_from_dirty_hints
from .attachment_runtime import capture_attachment_from_link
from .bound_objects import set_geometry_object, set_transform_object
from .common import find_geometry_mesh_scp_obj, find_scp_by_id, find_transform_scp_obj, is_transform_scp_obj, scp_for_object
from .link_state import restore_link_state, snapshot_link_state
from .lookup import activate_scp, effective_parent_obj, set_parent_relation, would_create_parent_cycle
from .object_colors import enable_object_color_view
from .object_roles import create_scp


def execute_mark_scp(operator, context):
    root, obj = _mark_inputs(operator, context)
    if root is None or obj is None:
        return {"CANCELLED"}
    return _mark_object(operator, context, root, obj)


def _mark_inputs(operator, context):
    root = get_af_root(context.scene)
    if root is None:
        return _report_error(operator, "No AF_ROOT found in scene."), None
    obj = context.active_object
    if obj is None or obj.type != "MESH" or obj.get("af_scp_mirror"):
        return _report_error(operator, _mark_error_message(obj)), None
    if scp_for_object(root, obj) is not None:
        return _report_error(operator, "Object already belongs to an SCP."), None
    return root, obj


def _mark_error_message(obj):
    if obj is None or obj.type != "MESH":
        return "Select a mesh object first."
    return "Cannot mark mirror object as SCP."


def _report_error(operator, message):
    if operator is not None:
        operator.report({"ERROR"}, message)
    return None


def _mark_object(operator, context, root, obj):
    scp = create_scp(root, obj.name)
    set_transform_object(root, scp, obj)
    set_geometry_object(root, scp, obj)
    enable_object_color_view(context)
    if not _assign_optional_parent(operator, context, root, scp):
        return {"CANCELLED"}
    activate_scp(root, scp.id)
    _sync_mark(context, scp.id)
    operator.report({"INFO"}, f"Marked '{obj.name}' as {scp.id}")
    return {"FINISHED"}


def _assign_optional_parent(operator, context, root, scp):
    child_obj = getattr(scp, "transform_object_ref", None)
    parent_obj = effective_parent_obj(context.scene, root)
    if parent_obj is None:
        set_parent_relation(child_obj, scp, None)
        return True
    if _would_reject_parent(operator, root, scp.id, parent_obj):
        return False
    return _set_parent_with_capture(operator, context, scp, child_obj, parent_obj)


def _would_reject_parent(operator, root, child_id, parent_obj):
    parent_id = str(parent_obj.get("af_scp_id") or "")
    if not would_create_parent_cycle(root, child_id, parent_id):
        return False
    operator.report({"ERROR"}, "Parent relation would create a cycle.")
    return True


def _set_parent_with_capture(operator, context, child_scp, child_obj, parent_obj):
    snapshot = snapshot_link_state(child_scp)
    set_parent_relation(child_obj, child_scp, parent_obj)
    root_name = get_af_root(context.scene).name
    child_geo = find_geometry_mesh_scp_obj(context.scene, root_name, child_scp.id)
    parent_geo = find_geometry_mesh_scp_obj(context.scene, root_name, parent_obj.get("af_scp_id"))
    if child_geo and parent_geo and capture_attachment_from_link(child_scp, child_obj, child_geo, parent_geo):
        return True
    restore_link_state(child_scp, snapshot)
    operator.report({"ERROR"}, "Failed to capture attachment from child face center.")
    return False


def _sync_mark(context, scp_id):
    sync_from_dirty_hints(root=get_af_root(context.scene), scene=context.scene, dirty_hints=dirty_hints_for("SCP", {scp_id}), source="operator", event_type="MARK")


def execute_set_scp_parent(operator, context):
    root = get_af_root(context.scene)
    child_obj, child_scp = _active_child(operator, context, root)
    if child_obj is None or child_scp is None:
        return {"CANCELLED"}
    return _apply_parent_target_change(operator, context, root, child_obj, child_scp, getattr(context.scene, "af_scp_parent_obj", None))


def execute_reparent_scp(operator, context, child_scp_id, parent_scp_id=""):
    root = get_af_root(context.scene)
    child_obj, child_scp = _child_by_id(operator, context, root, child_scp_id)
    parent_obj = _parent_by_id(operator, context, root, parent_scp_id)
    bad_parent = str(parent_scp_id or "") and parent_obj is None
    if child_obj is None or child_scp is None or bad_parent:
        return {"CANCELLED"}
    return _apply_parent_target_change(operator, context, root, child_obj, child_scp, parent_obj)


def _active_child(operator, context, root):
    active_obj = context.active_object
    child_scp = None if root is None else scp_for_object(root, active_obj)
    child_obj = None if child_scp is None else find_transform_scp_obj(context.scene, root.name, child_scp.id)
    if root is None or child_scp is None or child_obj is None:
        return _report_error_obj(operator, "Active object must belong to an SCP.")
    if child_scp is None:
        return _report_error_obj(operator, "Active SCP entry not found.")
    return child_obj, child_scp


def _report_error_obj(operator, message):
    if operator is not None:
        operator.report({"ERROR"}, message)
    return None, None


def _child_by_id(operator, context, root, scp_id):
    child_scp = None if root is None else find_scp_by_id(root, scp_id)
    child_obj = None if child_scp is None else find_transform_scp_obj(context.scene, root.name, child_scp.id)
    if child_scp is None or child_obj is None:
        return _report_error_obj(operator, "Target SCP not found.")
    return child_obj, child_scp


def _parent_by_id(operator, context, root, parent_scp_id):
    pid = str(parent_scp_id or "")
    if not pid:
        return None
    parent_obj = None if root is None else find_transform_scp_obj(context.scene, root.name, pid)
    if parent_obj is None and operator is not None:
        operator.report({"ERROR"}, "Target parent SCP has no transform object.")
    return parent_obj


def _apply_parent_target_change(operator, context, root, child_obj, child_scp, parent_obj):
    if _invalid_parent(operator, root, child_scp.id, parent_obj):
        return {"CANCELLED"}
    if parent_obj is None:
        set_parent_relation(child_obj, child_scp, None)
    elif not _set_parent_with_capture(operator, context, child_scp, child_obj, parent_obj):
        return {"CANCELLED"}
    _sync_parent(context, child_scp.id)
    return {"FINISHED"}


def _invalid_parent(operator, root, child_id, parent_obj):
    if parent_obj is None:
        return False
    if not is_transform_scp_obj(parent_obj, root.name):
        operator.report({"ERROR"}, "Parent must be another SCP transform object.")
        return True
    return _would_reject_parent(operator, root, child_id, parent_obj)


def _sync_parent(context, child_id):
    sync_from_dirty_hints(root=get_af_root(context.scene), scene=context.scene, dirty_hints=dirty_hints_for("SCP", {child_id}), source="operator", event_type="UPDATE")
