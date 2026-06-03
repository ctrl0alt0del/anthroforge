from ..selection import get_active_scp
from ..scp_runtime.common import scp_for_object
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
