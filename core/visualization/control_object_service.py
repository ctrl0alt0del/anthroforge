from ..selection import get_active_scp
from ..scp_runtime.common import find_scp_by_id, scp_for_object
from .scp_control_helpers import mark_scp_control_object
from .control_object_shortcuts import toggle_axis_shortcut


def selected_object(context):
    return getattr(context, "active_object", None)


def picked_scp(root, context):
    picker = getattr(context.scene, "af_control_scp_obj", None)
    if picker is not None:
        scp = scp_for_object(root, picker)
        if scp is not None:
            return scp
    return get_active_scp(root, context)


def _parent_keep_world(obj, parent):
    if obj is None or parent is None or obj == parent:
        return False
    world = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted()
    obj.matrix_world = world
    return True


def _clear_parent_keep_world(obj, parent):
    if obj is None or parent is None or getattr(obj, "parent", None) != parent:
        return False
    world = obj.matrix_world.copy()
    obj.parent = None
    obj.matrix_world = world
    return True


def _scp_for_control(root, context, obj):
    sid = "" if obj is None else str(obj.get("af_scp_id") or "")
    if sid:
        scp = find_scp_by_id(root, sid)
        if scp is not None:
            return scp
    return picked_scp(root, context)


def control_apply_parent_state(root, context):
    obj = selected_object(context)
    if root is None or obj is None:
        return False
    scp = _scp_for_control(root, context, obj)
    if scp is None:
        return False
    parent = getattr(scp, "transform_object_ref", None)
    return bool(parent is not None and getattr(obj, "parent", None) == parent)


def set_selected_control_parent_applied(root, context, enabled):
    obj = selected_object(context)
    if root is None or obj is None:
        return False, "No selected control object."
    scp = _scp_for_control(root, context, obj)
    if scp is None:
        return False, "Could not resolve SCP for selected control object."
    parent = getattr(scp, "transform_object_ref", None)
    if parent is None:
        return False, "Resolved SCP has no transform object to parent to."
    if obj == parent:
        return False, "Selected object is already the SCP transform object."
    if bool(enabled):
        _parent_keep_world(obj, parent)
    else:
        _clear_parent_keep_world(obj, parent)
    return True, ""


def mark_selected_scp_control(root, context):
    obj = selected_object(context)
    if root is None or obj is None:
        return False, "No selected object."
    scp = picked_scp(root, context)
    scp_id = "" if scp is None else str(getattr(scp, "id", "") or "")
    if not scp_id:
        return False, "Pick an SCP object first."
    mark_scp_control_object(obj, root, scp_id)
    return True, ""


def toggle_selected_control_axis_shortcut(root, context, axis):
    obj = selected_object(context)
    if root is None or obj is None:
        return False, "No selected object."
    scp = picked_scp(root, context)
    fallback = ("SCP", str(getattr(scp, "id", "") or "")) if scp is not None else ("NONE", "")
    return toggle_axis_shortcut(root, obj, axis, fallback_owner=fallback)
