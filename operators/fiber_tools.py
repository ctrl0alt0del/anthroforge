import bpy
from bpy_extras import view3d_utils

from ..core.scp_proxy.consts import ATTR_SLOT, FLAG as PROXY_FLAG, SIDE_KEY, SIDE_MIRRORED
from ..core.scp_proxy.session import proxy_sources
from ..core.scp_runtime.common import scp_prop_map
from ..core.scp_runtime.runtime_state import mirror_effective_axis, mirror_source_id
from ..core.visualization.mirror_rules import mirror_matrix
from ..app.use_cases.fiber_tools import (
    add_fiber_touch_point,
    add_fiber_touch_point_at_world,
    clear_fiber_warm_start,
    recompute_fiber,
    remove_fiber_touch_point,
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


def _ray_from_event(context, event):
    region, rv3d = _view_window(context)
    if region is None or rv3d is None:
        return None
    coord = (event.mouse_x - region.x, event.mouse_y - region.y)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    return origin, direction


def _scp_id_from_obj(root, obj):
    valid = obj.get("af_root_name") == root.name and obj.get("af_scp_bound")
    valid = valid and obj.get("af_scp_geometry") and not obj.get("af_scp_mirror")
    return str(obj.get("af_scp_id", "") or "") if valid else ""


def _raycast_scp(context, event, candidates=()):
    ray = _ray_from_event(context, event)
    return None if ray is None else _closest_scp_hit(ray, candidates)


def _pick_candidates(context):
    root = root_for_context(context)
    if root is None:
        return ()
    return tuple(_candidate_row(root, obj) for obj in context.scene.objects if _is_pick_candidate(context, root, obj))


def _is_pick_candidate(context, root, obj):
    if _is_proxy_candidate(root, obj):
        return _visible_for_pick(context, obj)
    valid = getattr(obj, "type", "") == "MESH" and _scp_id_from_obj(root, obj)
    return bool(valid and _visible_for_pick(context, obj))


def _is_proxy_candidate(root, obj):
    valid = getattr(obj, "type", "") == "MESH" and obj.get(PROXY_FLAG)
    return bool(valid and obj.get("af_root_name") == root.name)


def _visible_for_pick(context, obj):
    try:
        return bool(obj.visible_get(view_layer=context.view_layer))
    except Exception:
        return not bool(obj.hide_get())


def _candidate_row(root, obj):
    payload = _proxy_slot_payload(root, obj) if _is_proxy_candidate(root, obj) else _scp_id_from_obj(root, obj)
    kind = "PROXY" if _is_proxy_candidate(root, obj) else "SCP"
    return (kind, obj, obj.matrix_world.copy(), obj.matrix_world.inverted().copy(), payload)


def _closest_scp_hit(ray, candidates):
    hits = tuple(hit for hit in (_object_scp_hit(row, *ray) for row in tuple(candidates or ())) if hit is not None)
    return None if not hits else _pick_payload(min(hits, key=lambda item: item[2]))


def _object_scp_hit(row, origin, direction):
    kind, obj, matrix_world, world_inv, payload = row
    local_ray = _local_ray(world_inv, origin, direction)
    if local_ray is None:
        return None
    hit, loc, _normal, face = obj.ray_cast(*local_ray)
    if not hit:
        return None
    world = matrix_world @ loc
    scp_id, attach_world = _row_pick(kind, obj, payload, face, world)
    return None if not scp_id else (scp_id, attach_world, (world - origin).length, world)


def _local_ray(world_inv, origin, direction):
    local_origin = world_inv @ origin
    local_direction = world_inv.to_3x3() @ direction
    if local_direction.length <= 1.0e-9:
        return None
    return local_origin, local_direction.normalized()


def _row_pick(kind, obj, payload, face, world):
    if kind == "SCP":
        return payload, world
    source = _proxy_source_for_face(obj, payload, face)
    return ("", world) if source is None else (source[0], _proxy_world_to_source(source, world))


def _pick_payload(hit):
    return hit[0], hit[1].copy(), hit[3].copy()


def _proxy_slot_payload(root, obj):
    rows = (_proxy_slot_row(root, obj, row) for row in proxy_sources(obj))
    return {slot: data for slot, data in rows if slot >= 0 and data[0]}


def _proxy_slot_row(root, obj, row):
    try:
        slot = int(row.get("slot", -1))
    except Exception:
        slot = -1
    sid = str(row.get("scp_id", "") or "")
    return slot, (sid, _proxy_unmirror_matrix(root, obj, sid))


def _proxy_unmirror_matrix(root, obj, scp_id):
    if obj.get(SIDE_KEY) != SIDE_MIRRORED:
        return None
    scp = scp_prop_map(root).get(str(scp_id))
    source = None if scp is None else scp_prop_map(root).get(mirror_source_id(scp))
    origin = (0.0, 0.0, 0.0) if source is None else tuple(getattr(source, "mirror_origin", (0.0, 0.0, 0.0)))
    return None if source is None else mirror_matrix(mirror_effective_axis(scp), origin)


def _proxy_source_for_face(obj, payload, face_index):
    slot = _proxy_face_slot(obj, face_index)
    return None if slot is None else payload.get(int(slot))


def _proxy_face_slot(obj, face_index):
    poly = _face_poly(obj, face_index)
    attr = None if poly is None else obj.data.attributes.get(ATTR_SLOT)
    if attr is None:
        return None
    slots = [int(attr.data[int(v)].value) for v in poly.vertices]
    return None if not slots else max(set(slots), key=slots.count)


def _face_poly(obj, face_index):
    index = int(face_index)
    polys = getattr(getattr(obj, "data", None), "polygons", ())
    return polys[index] if 0 <= index < len(polys) else None


def _proxy_world_to_source(source, world):
    matrix = source[1]
    return world if matrix is None else matrix @ world


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
