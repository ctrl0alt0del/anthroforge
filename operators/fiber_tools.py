import bpy
from ..core.scp_runtime.viewport_picker import pick_candidates, raycast_scp
from ..app.use_cases.fiber_tools import (
    add_fiber_touch_point,
    add_fiber_touch_point_at_world,
    clear_fiber_warm_start,
    move_fiber_touch_point,
    recompute_fiber,
    remove_fiber_touch_point,
    restore_legacy_fiber,
)
from ..app.queries.root import root_for_context

_NAV_EVENT_TYPES = {
    "MIDDLEMOUSE",
    "WHEELUPMOUSE",
    "WHEELDOWNMOUSE",
    "WHEELINMOUSE",
    "WHEELOUTMOUSE",
    "TRACKPADPAN",
    "TRACKPADZOOM",
}


def _finish(operator, result):
    if result.message:
        operator.report({result.level}, result.message)
    return {"FINISHED"} if result.ok else {"CANCELLED"}


def _status(context, text):
    try:
        context.window.status_text_set(text)
    except Exception:
        pass


def _pass_through_event(event):
    event_type = str(getattr(event, "type", "") or "")
    return event_type in _NAV_EVENT_TYPES or event_type.startswith("NDOF_")


def _view_window(context):
    area = getattr(context, "area", None)
    if area is None or area.type != "VIEW_3D":
        return None, None
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    space = next((s for s in area.spaces if s.type == "VIEW_3D"), None)
    return region, getattr(space, "region_3d", None)


def _raycast_scp(context, event, candidates=()):
    return raycast_scp(context, event, candidates)


def _pick_candidates(context):
    root = root_for_context(context)
    return pick_candidates(context, root, include_muscles=True)


def _set_modal_cursor(context):
    try:
        context.window.cursor_modal_set("CROSSHAIR")
    except Exception:
        pass


def _restore_modal_cursor(context):
    try:
        context.window.cursor_modal_restore()
    except Exception:
        pass


def _tag_redraw(context):
    area = getattr(context, "area", None)
    if area is not None:
        area.tag_redraw()


def _add_touch_preview(operator, context):
    operator._hover_pick = None
    operator._hover_xy = None
    operator._pick_candidates = _pick_candidates(context)
    operator._draw_handler = bpy.types.SpaceView3D.draw_handler_add(
        _draw_touch_preview, (operator,), "WINDOW", "POST_VIEW"
    )


def _remove_touch_preview(operator):
    handler = getattr(operator, "_draw_handler", None)
    if handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")
    operator._draw_handler = None


def _end_touch_preview(operator, context):
    _remove_touch_preview(operator)
    _status(context, None)
    _restore_modal_cursor(context)
    _tag_redraw(context)


def _update_touch_preview(operator, context, event):
    xy = (event.mouse_x, event.mouse_y)
    if xy == getattr(operator, "_hover_xy", None):
        return
    operator._hover_xy = xy
    operator._hover_pick = _raycast_scp(context, event, getattr(operator, "_pick_candidates", ()))
    _tag_redraw(context)


def _draw_touch_preview(operator):
    picked = getattr(operator, "_hover_pick", None)
    if picked is None:
        return
    _draw_preview_point(picked[2], 15.0, (0.0, 0.0, 0.0, 0.8))
    _draw_preview_point(picked[2], 9.0, (0.1, 1.0, 1.0, 1.0))


def _draw_preview_point(point, size, color):
    gpu, batch_for_shader = _gpu_tools()
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "POINTS", {"pos": [point]})
    _configure_point_draw(gpu, size)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    _restore_point_draw(gpu)


def _gpu_tools():
    import gpu
    from gpu_extras.batch import batch_for_shader

    return gpu, batch_for_shader


def _configure_point_draw(gpu, size):
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    gpu.state.point_size_set(float(size))


def _restore_point_draw(gpu):
    gpu.state.point_size_set(1.0)
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.blend_set("NONE")


class AF_OT_ClearFiberWarmStart(bpy.types.Operator):
    bl_idname = "af.clear_fiber_warm_start"
    bl_label = "Clear Warm Start"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        return _finish(self, clear_fiber_warm_start(context, self.fiber_id))


class AF_OT_RecomputeFiber(bpy.types.Operator):
    bl_idname = "af.recompute_fiber"
    bl_label = "Recompute Fiber"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        return _finish(self, recompute_fiber(context, self.fiber_id))


class AF_OT_RestoreLegacyFiber(bpy.types.Operator):
    bl_idname = "af.restore_legacy_fiber"
    bl_label = "Restore Legacy Shape"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        return _finish(self, restore_legacy_fiber(context, self.fiber_id))


class AF_OT_AddFiberTouchPoint(bpy.types.Operator):
    bl_idname = "af.add_fiber_touch_point"
    bl_label = "Add Mid Touch Point"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")

    def invoke(self, context, event):
        if _view_window(context) == (None, None):
            self.report({"WARNING"}, "Run Add Mid Touch Point from a 3D View.")
            return {"CANCELLED"}
        _status(context, "Click an SCP geometry surface to add a mid touch point. Esc/RMB cancels.")
        _set_modal_cursor(context)
        _add_touch_preview(self, context)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            _end_touch_preview(self, context)
            return {"CANCELLED"}
        if _pass_through_event(event):
            return {"PASS_THROUGH"}
        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            _update_touch_preview(self, context, event)
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            return self._confirm_pick(context, event)
        return {"RUNNING_MODAL"}

    def _confirm_pick(self, context, event):
        _update_touch_preview(self, context, event)
        picked = getattr(self, "_hover_pick", None)
        if picked is None:
            self.report({"WARNING"}, "Click a valid SCP geometry surface.")
            return {"RUNNING_MODAL"}
        result = add_fiber_touch_point_at_world(context, self.fiber_id, picked[0], picked[1])
        _end_touch_preview(self, context)
        return _finish(self, result)

    def execute(self, context):
        return _finish(self, add_fiber_touch_point(context, self.fiber_id))


class AF_OT_RemoveFiberTouchPoint(bpy.types.Operator):
    bl_idname = "af.remove_fiber_touch_point"
    bl_label = "Remove Mid Touch Point"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")
    touch_index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        return _finish(self, remove_fiber_touch_point(context, self.fiber_id, self.touch_index))


class AF_OT_MoveFiberTouchPoint(bpy.types.Operator):
    bl_idname = "af.move_fiber_touch_point"
    bl_label = "Move Mid Touch Point"
    bl_options = {"REGISTER"}

    fiber_id: bpy.props.StringProperty(default="")
    touch_index: bpy.props.IntProperty(default=-1)
    direction: bpy.props.IntProperty(default=0)

    def execute(self, context):
        return _finish(self, move_fiber_touch_point(context, self.fiber_id, self.touch_index, self.direction))
