import math

import bpy
from mathutils import Vector

from ..app.use_cases.action_library_quick_hook import commit_quick_hook, name_quick_hook_control, quick_hook_draft
from ..core.action_library_quick_hook import FALLOFF_TYPES, quick_hook_influence, quick_hook_preview_weights, reusable_quick_hook


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
    result = _end_modal(operator, context, result)
    if ok:
        _begin_name_step(operator, context, operator._quick_hook_draft)
    return result


def _begin_name_step(operator, context, draft):
    row = reusable_quick_hook(context.scene, draft.geometry, draft.scp_id)
    if row is None:
        return operator.report({"WARNING"}, "Hook created, but its naming step could not start.")
    scene_name, control_name, geometry_name = context.scene.name, row.control.name, draft.geometry.name
    callback = lambda: _open_quick_hook_name(scene_name, control_name, geometry_name)
    _register_quick_hook_timer(callback)


def _open_quick_hook_name(scene_name, control_name, geometry_name):
    scene = bpy.data.scenes.get(str(scene_name or ""))
    control = None if scene is None else scene.objects.get(str(control_name or ""))
    window, area, region = _shortcut_wizard_window(scene)
    if control is None or window is None or area is None or region is None:
        return None
    _invoke_quick_hook_name(window, area, region, control.name, geometry_name)
    return None


def _invoke_quick_hook_name(window, area, region, control_name, geometry_name):
    try:
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.af.name_quick_scp_hook("INVOKE_DEFAULT", control_object_name=control_name, geometry_object_name=geometry_name, default_name=control_name)
    except Exception as exc:
        print(f"AnthroForge Quick Hook: naming could not start: {exc}")


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


def invoke_quick_hook_name(operator, context):
    operator.hook_name = ""
    return context.window_manager.invoke_props_dialog(operator, width=360, title="Name Quick Hook", confirm_text="Continue")


def draw_quick_hook_name(operator):
    operator.layout.prop(operator, "hook_name", text="Hook Name")
    operator.layout.label(text=f'Leave blank to use "{operator.default_name}".', icon="INFO")


def execute_quick_hook_name(operator, context):
    control, error = name_quick_hook_control(context, operator.geometry_object_name, operator.control_object_name, operator.default_name, operator.hook_name)
    if error:
        operator.report({"ERROR"}, error)
        return {"CANCELLED"}
    _activate_quick_hook_control(context, control)
    _schedule_shortcut_wizard(context, control)
    return {"FINISHED"}


def _activate_quick_hook_control(context, control):
    active = getattr(context, "active_object", None)
    if active is not None and getattr(active, "mode", "OBJECT") != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in tuple(getattr(context, "selected_objects", ()) or ()):
        obj.select_set(False)
    control.select_set(True)
    context.view_layer.objects.active = control


def _schedule_shortcut_wizard(context, control):
    scene_name, control_name = context.scene.name, control.name
    callback = lambda: _open_shortcut_wizard(scene_name, control_name)
    _register_quick_hook_timer(callback)


def _register_quick_hook_timer(callback):
    bpy.app.timers.register(callback, first_interval=0.0)


def _open_shortcut_wizard(scene_name, control_name):
    scene = bpy.data.scenes.get(str(scene_name or ""))
    control = None if scene is None else scene.objects.get(str(control_name or ""))
    window, area, region = _shortcut_wizard_window(scene)
    if control is None or window is None or area is None or region is None:
        return None
    _invoke_shortcut_wizard(scene, control, window, area, region)
    return None


def _invoke_shortcut_wizard(scene, control, window, area, region):
    try:
        with bpy.context.temp_override(window=window, area=area, region=region, active_object=control, object=control):
            bpy.ops.af.shortcut_wizard("INVOKE_DEFAULT", wildcard_value=str(control.name))
    except Exception as exc:
        print(f"AnthroForge Quick Hook: Shortcut Wizard could not start: {exc}")


def _shortcut_wizard_window(scene):
    manager = getattr(bpy.context, "window_manager", None)
    windows = () if manager is None else tuple(manager.windows)
    window = next((item for item in windows if item.scene == scene), None)
    areas = () if window is None else tuple(window.screen.areas)
    area = next((item for item in areas if item.type == "VIEW_3D"), None)
    regions = () if area is None else tuple(area.regions)
    region = next((item for item in regions if item.type == "WINDOW"), None)
    return window, area, region


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
    color = (0.12, 0.8, 1.0, 0.38) if operator._quick_hook_armed else (0.55, 0.65, 0.7, 0.25)
    for axes in ((0, 1), (0, 2), (1, 2)):
        _draw_ring(draft, axes, color)
    _draw_center(draft, color)
    _draw_influence_preview(draft)


def _draw_influence_preview(draft):
    rows = _preview_rows(draft)
    if not rows:
        return
    heat = [_heat_color(row[2]) for row in rows]
    ghost = [_ghost_color(row[2]) for row in rows]
    _draw_preview_faces(draft, rows, False)
    _draw_preview_faces(draft, rows, True)
    _draw_outlined_points([row[0] for row in rows], heat, 12.0)
    _draw_connectors(rows)
    _draw_ghost_edges(draft, rows)
    _draw_test_tug(draft)
    _draw_outlined_points([row[1] for row in rows], ghost, 10.0)


def _draw_preview_faces(draft, rows, ghost):
    points, colors = [], []
    slot = 1 if ghost else 0
    for triangle in draft.preview_faces:
        for index in triangle:
            points.append(rows[index][slot])
            colors.append(_preview_face_color(rows[index][2], ghost))
    _draw_colored("TRIS", points, colors, 1.0)


def _preview_face_color(weight, ghost):
    value = min(1.0, max(0.0, float(weight)))
    if ghost:
        return 0.12, 0.95, 1.0, 0.12 + value * 0.18
    color = _heat_color(value)
    return color[0], color[1], color[2], 0.2 + value * 0.3


def _draw_outlined_points(points, colors, size):
    outline = [(0.015, 0.02, 0.025, 0.95)] * len(points)
    _draw_colored("POINTS", points, outline, size + 5.0)
    _draw_colored("POINTS", points, colors, size)


def _preview_rows(draft):
    weights = quick_hook_preview_weights(draft)
    matrix, direction = draft.geometry.matrix_world, _view_up()
    distance = _preview_distance(draft)
    world = tuple(matrix @ Vector(point) for point in draft.preview_points)
    return tuple((point, point + direction * distance * weight, weight) for point, weight in zip(world, weights))


def _view_up():
    region = getattr(bpy.context, "region_data", None)
    matrix = getattr(region, "view_matrix", None)
    direction = Vector((0.0, 0.0, 1.0)) if matrix is None else matrix.inverted_safe().to_3x3() @ Vector((0.0, 1.0, 0.0))
    return direction.normalized() if direction.length_squared else Vector((0.0, 0.0, 1.0))


def _preview_distance(draft):
    scale = max((abs(value) for value in draft.geometry.matrix_world.to_scale()), default=1.0)
    return max(float(draft.pixel_scale) * 400.0 * scale * 0.08, 1.0e-4)


def _heat_color(weight):
    value = min(1.0, max(0.0, float(weight)))
    if value < 0.5:
        return _mix_color((0.08, 0.25, 0.8, 0.55), (1.0, 0.85, 0.08, 0.9), value * 2.0)
    return _mix_color((1.0, 0.85, 0.08, 0.9), (1.0, 0.12, 0.04, 1.0), value * 2.0 - 1.0)


def _mix_color(first, second, amount):
    return tuple(a + (b - a) * amount for a, b in zip(first, second))


def _ghost_color(weight):
    return 0.12, 0.95, 1.0, 0.22 + 0.68 * min(1.0, max(0.0, float(weight)))


def _draw_connectors(rows):
    points, colors = [], []
    for original, ghost, weight in rows:
        if (ghost - original).length_squared <= 1.0e-12:
            continue
        color = _ghost_color(weight)
        points.extend((original, ghost))
        colors.extend((color, color))
    _draw_colored("LINES", points, colors, 2.5)


def _draw_ghost_edges(draft, rows):
    points, colors = [], []
    for start, end in draft.preview_edges:
        if max(start, end) >= len(rows):
            continue
        points.extend((rows[start][1], rows[end][1]))
        colors.extend((_ghost_color(rows[start][2]), _ghost_color(rows[end][2])))
    _draw_colored("LINES", points, colors, 3.0)


def _draw_test_tug(draft):
    center = draft.geometry.matrix_world @ Vector(draft.center)
    end = center + _view_up() * _preview_distance(draft)
    color = (0.12, 0.95, 1.0, 0.65)
    _draw_uniform("LINES", (center, end), color, 2.0)
    _draw_uniform_points((end,), color, 7.0)


def _draw_ring(draft, axes, color):
    points = [_ring_point(draft, axes, step) for step in range(65)]
    _draw_uniform("LINE_STRIP", points, color, 1.0)


def _ring_point(draft, axes, step):
    angle = (math.tau * step) / 64.0
    point = Vector(draft.center)
    point[axes[0]] += math.cos(angle) * draft.radius
    point[axes[1]] += math.sin(angle) * draft.radius
    return draft.geometry.matrix_world @ point


def _draw_center(draft, color):
    point = draft.geometry.matrix_world @ Vector(draft.center)
    _draw_uniform_points((point,), color, 9.0)


def _draw_uniform(mode, points, color, width=1.0):
    if not points:
        return
    if mode in {"LINES", "LINE_STRIP"}:
        return _draw_uniform_polyline(mode, points, color, width)
    return _draw_uniform_primitive(mode, points, color)


def _draw_uniform_primitive(mode, points, color):
    gpu, batch_for_shader = _gpu_tools()
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    shader.bind()
    shader.uniform_float("color", color)
    batch_for_shader(shader, mode, {"pos": points}).draw(shader)
    gpu.state.blend_set("NONE")


def _draw_uniform_polyline(mode, points, color, width):
    gpu, batch_for_shader = _gpu_tools()
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    _prepare_polyline(shader, width)
    shader.uniform_float("color", color)
    batch_for_shader(shader, mode, {"pos": points}).draw(shader)
    gpu.state.blend_set("NONE")


def _draw_colored(mode, points, colors, size):
    if not points:
        return
    if mode == "POINTS":
        return _draw_colored_points(points, colors, size)
    if mode in {"LINES", "LINE_STRIP"}:
        return _draw_colored_polyline(mode, points, colors, size)
    return _draw_colored_primitive(mode, points, colors)


def _draw_uniform_points(points, color, size):
    if not points:
        return
    gpu, batch_for_shader = _gpu_tools()
    shader = gpu.shader.from_builtin("POINT_UNIFORM_COLOR")
    _prepare_overlay(gpu)
    shader.bind()
    shader.uniform_float("color", color)
    shader.uniform_float("size", size)
    batch_for_shader(shader, "POINTS", {"pos": points}).draw(shader)
    gpu.state.blend_set("NONE")


def _draw_colored_points(points, colors, size):
    gpu, batch_for_shader = _gpu_tools()
    shader = gpu.shader.from_builtin("POINT_FLAT_COLOR")
    _prepare_overlay(gpu)
    shader.bind()
    shader.uniform_float("size", size)
    batch_for_shader(shader, "POINTS", {"pos": points, "color": colors}).draw(shader)
    gpu.state.blend_set("NONE")


def _draw_colored_polyline(mode, points, colors, width):
    gpu, batch_for_shader = _gpu_tools()
    shader = gpu.shader.from_builtin("POLYLINE_SMOOTH_COLOR")
    _prepare_polyline(shader, width)
    batch_for_shader(shader, mode, {"pos": points, "color": colors}).draw(shader)
    gpu.state.blend_set("NONE")


def _draw_colored_primitive(mode, points, colors):
    gpu, batch_for_shader = _gpu_tools()
    shader = gpu.shader.from_builtin("SMOOTH_COLOR")
    _prepare_overlay(gpu)
    shader.bind()
    batch_for_shader(shader, mode, {"pos": points, "color": colors}).draw(shader)
    gpu.state.blend_set("NONE")


def _prepare_polyline(shader, width):
    gpu, _batch_for_shader = _gpu_tools()
    _prepare_overlay(gpu)
    shader.bind()
    shader.uniform_float("viewportSize", _viewport_size())
    shader.uniform_float("lineWidth", float(width))


def _prepare_overlay(gpu):
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")


def _viewport_size():
    region = getattr(bpy.context, "region", None)
    return float(getattr(region, "width", 1.0)), float(getattr(region, "height", 1.0))


def _draw_status(operator):
    draft = getattr(operator, "_quick_hook_draft", None)
    if draft is None:
        return
    _draw_falloff_graph(draft)
    text = "Move pointer into viewport" if not operator._quick_hook_armed else _value_text(draft)
    _draw_text(text, 24, 38, 14, (0.9, 0.95, 1.0, 1.0))
    if operator._quick_hook_armed:
        _draw_text("Mouse X radius · Y strength · Wheel falloff · LMB confirm · Esc cancel", 24, 18, 11, (0.72, 0.82, 0.9, 1.0))


def _draw_falloff_graph(draft):
    x, y, width, height = 24.0, 76.0, 150.0, 48.0
    _draw_uniform("TRIS", _graph_background(x, y, width, height), (0.02, 0.03, 0.05, 0.72))
    _draw_uniform("LINES", _graph_border(x, y, width, height), (0.45, 0.55, 0.62, 0.7))
    points = [_graph_point(draft, x, y, width, height, index) for index in range(49)]
    _draw_uniform("LINE_STRIP", points, (1.0, 0.45, 0.08, 1.0), 2.0)
    _draw_text(f"{draft.falloff.replace('_', ' ').title()} influence", 28, 130, 11, (0.8, 0.88, 0.94, 1.0))
    _draw_text("Blue low · Red high · Cyan ghost", 28, 61, 10, (0.72, 0.82, 0.9, 1.0))


def _graph_background(x, y, width, height):
    return ((x, y, 0.0), (x + width, y, 0.0), (x + width, y + height, 0.0), (x, y, 0.0), (x + width, y + height, 0.0), (x, y + height, 0.0))


def _graph_border(x, y, width, height):
    return ((x, y, 0.0), (x + width, y, 0.0), (x + width, y, 0.0), (x + width, y + height, 0.0), (x + width, y + height, 0.0), (x, y + height, 0.0), (x, y + height, 0.0), (x, y, 0.0))


def _graph_point(draft, x, y, width, height, index):
    fraction = index / 48.0
    weight = _graph_weight(draft, fraction)
    return x + width * fraction, y + height * weight, 0.0


def _graph_weight(draft, fraction):
    if draft.radius <= 0.0:
        return min(1.0, max(0.0, float(draft.strength)))
    return quick_hook_influence(fraction, 1.0, draft.falloff, draft.strength)


def _draw_text(text, x, y, size, color):
    import blf
    blf.position(0, x, y, 0)
    blf.size(0, size)
    blf.color(0, *color)
    blf.draw(0, text)


def _status_text(draft):
    return f"{_value_text(draft)} | X radius | Y strength | Wheel falloff | LMB/Enter confirm | Esc/RMB cancel"


def _value_text(draft):
    affected = sum(weight > 1.0e-4 for weight in quick_hook_preview_weights(draft))
    return f"Radius {draft.radius:.4g} · Strength {draft.strength:.2f} · {draft.falloff.replace('_', ' ').title()} · {affected}/{draft.selected_count} influenced"


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
