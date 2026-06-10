from ..queries.control_objects import active_object
from ..queries.root import has_root


def can_edit_control_objects(context):
    return has_root(context) and active_object(context) is not None


def mark_selected_control(context):
    return _run_control_action(context, lambda service, root, ctx: service.mark_selected_scp_control(root, ctx))


def toggle_control_axis(context, axis):
    value = str(axis or "")
    return _run_control_action(context, lambda service, root, ctx: service.toggle_selected_control_axis_shortcut(root, ctx, value))


def toggle_control_parent(context):
    return _run_control_action(context, _toggle_parent)


def _run_control_action(context, action):
    root = _root_for_context(context)
    return (False, "") if root is None else action(_control_service(), root, context)


def _toggle_parent(service, root, context):
    enabled = not service.control_apply_parent_state(root, context)
    return service.set_selected_control_parent_applied(root, context, enabled)


def _root_for_context(context):
    try:
        from ..queries.root import root_for_context
    except ImportError:
        from app.queries.root import root_for_context
    return root_for_context(context)


def _control_service():
    try:
        from ...core.visualization import control_object_service
    except ImportError:
        from core.visualization import control_object_service
    return control_object_service
