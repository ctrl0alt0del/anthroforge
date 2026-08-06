import bpy

from ..app.queries.root import root_for_context
from ..app.use_cases.action_library_quick_fiber import (
    capture_quick_fiber_point,
    commit_quick_fiber,
    quick_fiber_context_error,
)
from ..core.scp_runtime.viewport_picker import pick_candidates, raycast_scp


_NAVIGATION = {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "WHEELINMOUSE",
               "WHEELOUTMOUSE", "TRACKPADPAN", "TRACKPADZOOM"}


def invoke_quick_fiber(operator, context):
    error = quick_fiber_context_error(context)
    if error:
        operator.report({"WARNING"}, error)
        return {"CANCELLED"}
    _snapshot_context(operator, context)
    _ensure_object_mode(context)
    _start_modal(operator, context)
    context.window_manager.modal_handler_add(operator)
    return {"RUNNING_MODAL"}


def modal_quick_fiber(operator, context, event):
    if event.type in {"ESC", "RIGHTMOUSE"}:
        return _cancel_modal(operator, context)
    if event.type in _NAVIGATION or event.type.startswith("NDOF_"):
        return {"PASS_THROUGH"}
    if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
        _update_hover(operator, context, event)
    if event.type == "BACK_SPACE" and event.value == "PRESS":
        _remove_last(operator, context)
    if event.type == "LEFTMOUSE" and event.value == "PRESS":
        return _confirm_pick(operator, context, event)
    return {"RUNNING_MODAL"}


def cancel_quick_fiber(operator, context):
    _end_modal(operator, context)


def _start_modal(operator, context):
    operator._quick_fiber_points = []
    operator._quick_fiber_hover = None
    operator._quick_fiber_armed = False
    operator._quick_fiber_candidates = pick_candidates(context, root_for_context(context))
    operator._quick_fiber_view_draw = bpy.types.SpaceView3D.draw_handler_add(
        _draw_geometry, (operator,), "WINDOW", "POST_VIEW")
    operator._quick_fiber_text_draw = bpy.types.SpaceView3D.draw_handler_add(
        _draw_text, (operator,), "WINDOW", "POST_PIXEL")
    _set_cursor(context, "CROSSHAIR")
    _set_status(operator, context)


def _update_hover(operator, context, event):
    if not _inside_view(context, event):
        return
    operator._quick_fiber_armed = True
    operator._quick_fiber_hover = raycast_scp(
        context, event, getattr(operator, "_quick_fiber_candidates", ()))
    _set_status(operator, context)
    _tag_redraw(context)


def _confirm_pick(operator, context, event):
    if not operator._quick_fiber_armed or not _inside_view(context, event):
        return {"RUNNING_MODAL"}
    _update_hover(operator, context, event)
    point, error = capture_quick_fiber_point(context, operator._quick_fiber_hover)
    if error:
        operator.report({"WARNING"}, error)
        return {"RUNNING_MODAL"}
    if _point_rejected(operator, point):
        operator.report({"WARNING"}, "Choose a different surface point.")
        return {"RUNNING_MODAL"}
    return _use_point(operator, context, event, point)


def _use_point(operator, context, event, point):
    points = operator._quick_fiber_points
    if not points or bool(getattr(event, "shift", False)):
        points.append(point)
        _set_status(operator, context)
        _tag_redraw(context)
        return {"RUNNING_MODAL"}
    return _commit(operator, context, point)


def _commit(operator, context, insertion):
    result = commit_quick_fiber(context, tuple(operator._quick_fiber_points) + (insertion,))
    if not result.ok:
        operator.report({result.level}, result.message)
        return {"RUNNING_MODAL"}
    relaunch = _relaunch_spec(context)
    _end_modal(operator, context)
    _schedule_relaunch(relaunch)
    return {"FINISHED"}


def _point_rejected(operator, point):
    points = getattr(operator, "_quick_fiber_points", ())
    if not points:
        return False
    return (points[-1].visual_world - point.visual_world).length <= 1.0e-6


def _remove_last(operator, context):
    points = getattr(operator, "_quick_fiber_points", None)
    if points:
        points.pop()
    _set_status(operator, context)
    _tag_redraw(context)


def _cancel_modal(operator, context):
    restore = bool(getattr(operator, "restore_on_cancel", True))
    _end_modal(operator, context)
    if restore:
        _restore_context(operator, context)
    return {"CANCELLED"}


def _end_modal(operator, context):
    _remove_handler(operator, "_quick_fiber_view_draw", "WINDOW")
    _remove_handler(operator, "_quick_fiber_text_draw", "WINDOW")
    _set_window_status(context, None)
    _restore_cursor(context)
    _tag_redraw(context)


def _remove_handler(operator, attr, region):
    handler = getattr(operator, attr, None)
    if handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(handler, region)
    setattr(operator, attr, None)


def _snapshot_context(operator, context):
    operator._quick_fiber_old_active = _name(getattr(context, "active_object", None))
    operator._quick_fiber_old_selected = tuple(_name(obj) for obj in context.selected_objects)
    operator._quick_fiber_old_mode = str(getattr(context, "mode", "OBJECT") or "OBJECT")


def _restore_context(operator, context):
    for obj in tuple(getattr(context, "selected_objects", ()) or ()):
        obj.select_set(False)
    for name in getattr(operator, "_quick_fiber_old_selected", ()):
        obj = context.scene.objects.get(name)
        None if obj is None else obj.select_set(True)
    active = context.scene.objects.get(getattr(operator, "_quick_fiber_old_active", ""))
    if active is not None:
        context.view_layer.objects.active = active
    _restore_mode(context, getattr(operator, "_quick_fiber_old_mode", "OBJECT"))


def _ensure_object_mode(context):
    active = getattr(context, "active_object", None)
    if active is None or getattr(active, "mode", "OBJECT") == "OBJECT":
        return
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass


def _restore_mode(context, old_mode):
    active = getattr(context, "active_object", None)
    if active is None or not str(old_mode).startswith("EDIT"):
        return
    try:
        bpy.ops.object.mode_set(mode="EDIT")
    except Exception:
        pass


def _relaunch_spec(context):
    window, area = getattr(context, "window", None), getattr(context, "area", None)
    region = None if area is None else next((item for item in area.regions if item.type == "WINDOW"), None)
    ptr = lambda item: 0 if item is None else int(item.as_pointer())
    return context.scene.name, ptr(window), ptr(area), ptr(region)


def _schedule_relaunch(spec):
    def callback():
        _relaunch(*spec)
        return None
    bpy.app.timers.register(callback, first_interval=0.0)


def _relaunch(scene_name, window_ptr, area_ptr, region_ptr):
    override = _relaunch_override(scene_name, window_ptr, area_ptr, region_ptr)
    if override is None:
        return
    try:
        with bpy.context.temp_override(**override):
            bpy.ops.af.quick_fiber("INVOKE_DEFAULT", restore_on_cancel=False)
    except Exception as exc:
        print(f"AnthroForge Quick Fiber: continuous creation stopped: {exc}")


def _relaunch_override(scene_name, window_ptr, area_ptr, region_ptr):
    manager = getattr(bpy.context, "window_manager", None)
    window = next((item for item in manager.windows if item.as_pointer() == window_ptr), None)
    area = None if window is None else next((item for item in window.screen.areas if item.as_pointer() == area_ptr), None)
    region = None if area is None else next((item for item in area.regions if item.as_pointer() == region_ptr), None)
    scene = bpy.data.scenes.get(scene_name)
    return None if None in (window, area, region, scene) else {"window": window, "area": area, "region": region, "scene": scene}


def _set_status(operator, context):
    points = getattr(operator, "_quick_fiber_points", ())
    hover = getattr(operator, "_quick_fiber_hover", None)
    if not operator._quick_fiber_armed:
        text = "Move into the viewport to start Quick Fiber"
    elif not points:
        text = "Quick Fiber: click origin • Esc exits"
    else:
        text = "Quick Fiber: click insertion • Shift-click adds guide • Backspace removes"
    operator._quick_fiber_status = text + _hover_suffix(context, hover)
    _set_window_status(context, operator._quick_fiber_status)


def _hover_suffix(context, hover):
    if hover is None:
        return ""
    root = root_for_context(context)
    scp = next((item for item in root.af_scp_system.scps if item.id == hover[0]), None)
    label = hover[0] if scp is None else (scp.name or scp.id)
    return f" • Hover: {label}"


def _draw_geometry(operator):
    points = [item.visual_world for item in getattr(operator, "_quick_fiber_points", ())]
    hover = getattr(operator, "_quick_fiber_hover", None)
    if hover is not None:
        points.append(hover[2])
    if len(points) >= 2:
        _draw_line(points)
    _draw_markers(operator, hover)


def _draw_markers(operator, hover):
    points = getattr(operator, "_quick_fiber_points", ())
    if points:
        _draw_point(points[0].visual_world, 12.0, (0.1, 0.9, 1.0, 1.0))
    for point in points[1:]:
        _draw_point(point.visual_world, 11.0, (1.0, 0.55, 0.1, 1.0))
    if hover is not None:
        _draw_point(hover[2], 12.0, (1.0, 0.3, 0.05, 1.0))


def _draw_line(points):
    gpu, batch_for_shader = _gpu_tools()
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    coords = [value for pair in zip(points[:-1], points[1:]) for value in pair]
    batch = batch_for_shader(shader, "LINES", {"pos": coords})
    _draw_batch(gpu, shader, batch, (0.0, 0.0, 0.0, 0.85), line_width=5.0)
    _draw_batch(gpu, shader, batch, (0.1, 0.9, 1.0, 0.8), line_width=2.0)


def _draw_point(point, size, color):
    gpu, batch_for_shader = _gpu_tools()
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    outline = batch_for_shader(shader, "POINTS", {"pos": [point]})
    _draw_batch(gpu, shader, outline, (0.0, 0.0, 0.0, 0.85), point_size=size + 5.0)
    marker = batch_for_shader(shader, "POINTS", {"pos": [point]})
    _draw_batch(gpu, shader, marker, color, point_size=size)


def _draw_batch(gpu, shader, batch, color, point_size=1.0, line_width=1.0):
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    gpu.state.point_size_set(float(point_size))
    gpu.state.line_width_set(float(line_width))
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.point_size_set(1.0)
    gpu.state.line_width_set(1.0)
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.blend_set("NONE")


def _draw_text(operator):
    import blf
    text = str(getattr(operator, "_quick_fiber_status", "") or "")
    if not text:
        return
    blf.position(0, 24, 54, 0)
    blf.size(0, 14)
    blf.color(0, 0.85, 0.95, 1.0, 1.0)
    blf.draw(0, text)


def _gpu_tools():
    import gpu
    from gpu_extras.batch import batch_for_shader
    return gpu, batch_for_shader


def _inside_view(context, event):
    area = getattr(context, "area", None)
    region = None if area is None else next((item for item in area.regions if item.type == "WINDOW"), None)
    if area is None or area.type != "VIEW_3D" or region is None:
        return False
    x, y = int(event.mouse_x), int(event.mouse_y)
    return region.x <= x < region.x + region.width and region.y <= y < region.y + region.height


def _set_window_status(context, text):
    try:
        context.window.status_text_set(text)
    except Exception:
        pass


def _set_cursor(context, value):
    try:
        context.window.cursor_modal_set(value)
    except Exception:
        pass


def _restore_cursor(context):
    try:
        context.window.cursor_modal_restore()
    except Exception:
        pass


def _tag_redraw(context):
    area = getattr(context, "area", None)
    None if area is None else area.tag_redraw()


def _name(obj):
    return "" if obj is None else str(getattr(obj, "name", "") or "")
