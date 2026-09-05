from ..queries.root import root_for_context
from .results import failure, success

try:
    from ...core.visualization.category_visibility import CATEGORY_ROLES, set_category_visibility
except ImportError:
    from core.visualization.category_visibility import CATEGORY_ROLES, set_category_visibility


def set_vcp_category_visibility(context, category, hidden):
    root = root_for_context(context)
    layer = getattr(context, "view_layer", None)
    if root is None or layer is None or category not in CATEGORY_ROLES:
        return failure("No active AF root, view layer, or valid VCP category.")
    summary = set_category_visibility(context.scene, layer, root, category, hidden)
    _redraw_viewports(context)
    message = f"{summary.changed} changed; {summary.available} available"
    if summary.unavailable:
        message += f"; {summary.unavailable} unavailable in this view layer"
    return success(message, value=summary)


def _redraw_viewports(context):
    manager = getattr(context, "window_manager", None)
    for window in getattr(manager, "windows", ()):
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
