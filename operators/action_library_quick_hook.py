import math

import bpy
from mathutils import Vector

from ..app.use_cases.action_library_quick_hook import commit_quick_hook, quick_hook_draft
from ..core.action_library_quick_hook import FALLOFF_TYPES


_NAVIGATION = {"MIDDLEMOUSE", "TRACKPADPAN", "TRACKPADZOOM"}


def invoke_quick_hook(operator, context):
    draft, error = quick_hook_draft(context)
    if error:
        operator.report({"WARNING"}, error)
        return {"CANCELLED"}
    _start_modal(operator, context, draft)
    context.window_manager.modal_handler_add(operator)
    return {"RUNNING_MODAL"}


def _start_modal(operator, context, draft):
    operator._quick_hook_draft = draft
    operator._quick_hook_armed = False
    operator._quick_hook_xy = None
    operator._quick_hook_view_draw = bpy.types.SpaceView3D.draw_handler_add(_draw_geometry, (operator,), "WINDOW", "POST_VIEW")
    operator._quick_hook_text_draw = bpy.types.SpaceView3D.draw_handler_add(_draw_status, (operator,), "WINDOW", "POST_PIXEL")
    _set_cursor(context, "SCROLL_XY")
    _set_status(context, "Move into the viewport to tune Quick Hook. Esc/RMB cancels.")
    _tag_redraw(context)


def modal_quick_hook(operator, context, event):
    if event.type in {"ESC", "RIGHTMOUSE"}:
        return _end_modal(operator, context, {"CANCELLED"})
    if event.type in _NAVIGATION or event.type.startswith("NDOF_"):
        return {"PASS_THROUGH"}
    _arm_or_adjust(operator, context, event)
    if not getattr(operator, "_quick_hook_armed", False):
        return {"RUNNING_MODAL"}
    if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} and event.value == "PRESS":
        _cycle_falloff(operator, event.type == "WHEELUPMOUSE")
        _set_status(context, _status_text(operator._quick_hook_draft))
        _tag_redraw(context)
    if _confirm_event(event):
        return _confirm_modal(operator, context)
    return {"RUNNING_MODAL"}


def _arm_or_adjust(operator, context, event):
    if event.type not in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"} or not _inside_view(context, event):
        return
    xy = (int(event.mouse_x), int(event.mouse_y))
    if not operator._quick_hook_armed:
        operator._quick_hook_armed, operator._quick_hook_xy = True, xy
        _set_status(context, _status_text(operator._quick_hook_draft))
        return
    _adjust_draft(operator._quick_hook_draft, operator._quick_hook_xy, xy)
    operator._quick_hook_xy = xy
    _set_status(context, _status_text(operator._quick_hook_draft))
    _tag_redraw(context)


def _adjust_draft(draft, previous, current):
    dx, dy = current[0] - previous[0], current[1] - previous[1]
    draft.radius = max(0.0, draft.radius + dx * draft.pixel_scale)
    draft.strength = min(1.0, max(0.0, draft.strength + dy / 300.0))


def _cycle_falloff(operator, forward):
    draft = operator._quick_hook_draft
    index = FALLOFF_TYPES.index(draft.falloff) if draft.falloff in FALLOFF_TYPES else 0
    draft.falloff = FALLOFF_TYPES[(index + (1 if forward else -1)) % len(FALLOFF_TYPES)]


def _confirm_event(event):
    mouse = event.type == "LEFTMOUSE" and event.value == "PRESS"
    keyboard = event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS"
    return mouse or keyboard


def _confirm_modal(operator, context):
    ok, error = commit_quick_hook(context, operator._quick_hook_draft)
    result = {"FINISHED"} if ok else {"CANCELLED"}
    if error:
        operator.report({"ERROR"}, error)
    return _end_modal(operator, context, result)


def execute_quick_hook(operator, context):
    draft, error = quick_hook_draft(context)
    if error:
        operator.report({"ERROR"}, error)
        return {"CANCELLED"}
    ok, error = commit_quick_hook(context, draft)
    if error:
        operator.report({"ERROR"}, error)
    return {"FINISHED"} if ok else {"CANCELLED"}


def cancel_quick_hook(operator, context):
    _end_modal(operator, context, {"CANCELLED"})


def _end_modal(operator, context, result):
    _remove_handler(operator, "_quick_hook_view_draw", "WINDOW")
    _remove_handler(operator, "_quick_hook_text_draw", "WINDOW")
    _set_status(context, None)
    _restore_cursor(context)
    _tag_redraw(context)
    return result


def _remove_handler(operator, attr, region):
    handler = getattr(operator, attr, None)
    if handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(handler, region)
    setattr(operator, attr, None)


def _inside_view(context, event):
    area = getattr(context, "area", None)
    region = None if area is None else next((item for item in area.regions if item.type == "WINDOW"), None)
    if area is None or area.type != "VIEW_3D" or region is None:
        return False
    x, y = int(event.mouse_x), int(event.mouse_y)
    return region.x <= x < region.x + region.width and region.y <= y < region.y + region.height


def _draw_geometry(operator):
    draft = getattr(operator, "_quick_hook_draft", None)
    if draft is None:
        return
    color = (0.12, 0.8, 1.0, 0.85) if operator._quick_hook_armed else (0.55, 0.65, 0.7, 0.5)
    for axes in ((0, 1), (0, 2), (1, 2)):
        _draw_ring(draft, axes, color)
    _draw_center(draft, color)


def _draw_ring(draft, axes, color):
    points = [_ring_point(draft, axes, step) for step in range(65)]
    gpu, batch_for_shader = _gpu_tools()
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    shader.bind()
    shader.uniform_float("color", color)
    batch_for_shader(shader, "LINE_STRIP", {"pos": points}).draw(shader)
    gpu.state.blend_set("NONE")


def _ring_point(draft, axes, step):
    angle = (math.tau * step) / 64.0
    point = Vector(draft.center)
    point[axes[0]] += math.cos(angle) * draft.radius
    point[axes[1]] += math.sin(angle) * draft.radius
    return draft.geometry.matrix_world @ point


def _draw_center(draft, color):
    gpu, batch_for_shader = _gpu_tools()
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    point = draft.geometry.matrix_world @ Vector(draft.center)
    gpu.state.point_size_set(9.0)
    shader.bind()
    shader.uniform_float("color", color)
    batch_for_shader(shader, "POINTS", {"pos": [point]}).draw(shader)
    gpu.state.point_size_set(1.0)


def _draw_status(operator):
    import blf
    draft = getattr(operator, "_quick_hook_draft", None)
    text = "Move pointer into viewport" if not operator._quick_hook_armed else _status_text(draft)
    blf.position(0, 24, 42, 0)
    blf.size(0, 14)
    blf.color(0, 0.9, 0.95, 1.0, 1.0)
    blf.draw(0, text)


def _status_text(draft):
    return f"Radius {draft.radius:.4g} | Strength {draft.strength:.2f} | {draft.falloff} | LMB/Enter confirm | Esc/RMB cancel"


def _gpu_tools():
    import gpu
    from gpu_extras.batch import batch_for_shader
    return gpu, batch_for_shader


def _set_status(context, text):
    try:
        context.window.status_text_set(text)
    except Exception:
        pass


def _set_cursor(context, cursor):
    try:
        context.window.cursor_modal_set(cursor)
    except Exception:
        pass


def _restore_cursor(context):
    try:
        context.window.cursor_modal_restore()
    except Exception:
        pass


def _tag_redraw(context):
    area = getattr(context, "area", None)
    area.tag_redraw() if area is not None else None
