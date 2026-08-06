try:
    from ...core.vcp.runtime_state import (
        fiber_invalid_reason,
        fiber_recompute_status,
        reset_fiber_runtime,
    )
except ImportError:
    from core.vcp.runtime_state import (
        fiber_invalid_reason,
        fiber_recompute_status,
        reset_fiber_runtime,
    )
from ..queries.root import root_for_context
from .results import failure, success


def clear_fiber_warm_start(context, fiber_id=""):
    root = root_for_context(context)
    fiber, error = _resolved_fiber(root, fiber_id)
    if fiber is None:
        return failure(error)
    _fiber_sync().clear_solver_cache(fiber.id)
    _reset_fiber_stats(fiber)
    return success(f"Warm-start cache cleared for {fiber.id}", value=fiber)


def recompute_fiber(context, fiber_id="", max_passes=12):
    _ = max_passes
    root = root_for_context(context)
    fiber, error = _resolved_fiber(root, fiber_id)
    if fiber is None:
        return failure(error)
    request = _request_refinement()(root, context.scene, fiber, show_preview=False)
    if not request.ok:
        return failure(request.error or _invalid_message(fiber))
    return success(f"Refining {fiber.id} in the background", value=fiber)


def add_fiber_touch_point(context, fiber_id=""):
    root = root_for_context(context)
    resolved = _resolved_touch(context, root, fiber_id)
    if resolved is not None:
        fiber, scp_id, attach_param = resolved
        return _append_touch_result(context, root, fiber, ((scp_id, attach_param),))
    resolved, error = _resolved_touches(context, root, fiber_id)
    if resolved is None:
        return failure(error or "Select a fiber and a valid SCP geometry object.")
    return _append_touch_result(context, root, *resolved)


def add_fiber_touch_point_at_world(context, fiber_id, scp_id, point):
    root = root_for_context(context)
    fiber, error = _resolved_fiber(root, fiber_id)
    if fiber is None:
        return failure(error)
    spec = _world_touch_spec(root, context.scene, scp_id, point)
    if spec is None:
        return failure("Click a valid SCP geometry surface.")
    return _append_touch_result(context, root, fiber, (spec,))


def remove_fiber_touch_point(context, fiber_id="", touch_index=-1):
    root = root_for_context(context)
    fiber, error = _resolved_fiber(root, fiber_id)
    index = int(touch_index)
    if fiber is None:
        return failure(error)
    if index < 0 or index >= len(fiber.mid_touches):
        return failure("Invalid touch index.")
    fiber.mid_touches.remove(index)
    _set_prefer_bake(fiber, False)
    _fiber_sync().clear_solver_cache(fiber.id)
    _sync_entity(root, context.scene, "FIBER", {fiber.id}, bake=False)
    return success(value=fiber)


def move_fiber_touch_point(context, fiber_id="", touch_index=-1, direction=0):
    root = root_for_context(context)
    fiber, error = _resolved_fiber(root, fiber_id)
    index, target = int(touch_index), int(touch_index) + int(direction)
    if fiber is None:
        return failure(error)
    if not _valid_touch_move(fiber, index, target):
        return failure("Invalid touch move.")
    _remove_fiber_touch_handles(context.scene, root.name, fiber.id)
    fiber.mid_touches.move(index, target)
    return _touch_order_changed(context, root, fiber)


def _resolved_fiber(root, fiber_id):
    if root is None:
        return None, ""
    target_id = str(fiber_id or root.af_vcp_system.active_vcp_id or "")
    if not target_id:
        return None, "No active fiber."
    fiber = next((item for item in root.af_vcp_system.fibers if item.id == target_id), None)
    return (fiber, "") if fiber is not None else (None, "Fiber not found.")


def _reset_fiber_stats(fiber):
    reset_fiber_runtime(fiber)


def _set_prefer_bake(fiber, enabled):
    try:
        fiber["af_prefer_bake"] = bool(enabled)
    except Exception:
        return


def _invalid_attachment(fiber):
    return fiber_recompute_status(fiber) == "INVALID_ATTACHMENT"


def _invalid_message(fiber):
    return fiber_invalid_reason(fiber) or "Fiber attachment invalid."


def _resolved_touches(context, root, fiber_id):
    fiber, _error = _resolved_fiber(root, fiber_id)
    if fiber is None:
        return None, "No active fiber."
    touch_specs, error = _selected_touch_specs(context, root)
    if error:
        return None, error
    touch_specs = touch_specs or _default_touch_specs(context, root)
    return (None, "Select a fiber and a valid SCP geometry object.") if not touch_specs else ((fiber, touch_specs), "")


def _resolved_touch(context, root, fiber_id=""):
    resolved, _error = _resolved_touches(context, root, fiber_id)
    if resolved is None or len(resolved[1]) != 1:
        return None
    fiber, touch_specs = resolved
    return fiber, touch_specs[0][0], touch_specs[0][1]


def _append_touch_result(context, root, fiber, touch_specs):
    _append_touch_specs(fiber, touch_specs)
    return _touch_order_changed(context, root, fiber)


def _touch_order_changed(context, root, fiber):
    _set_prefer_bake(fiber, False)
    _fiber_sync().clear_solver_cache(fiber.id)
    _sync_entity(root, context.scene, "FIBER", {fiber.id}, bake=False)
    return success(value=fiber)


def _valid_touch_move(fiber, index, target):
    count = len(fiber.mid_touches)
    return 0 <= index < count and 0 <= target < count and index != target


def _remove_fiber_touch_handles(scene, root_name, fiber_id):
    import bpy

    for obj in tuple(getattr(scene, "objects", ()) or ()):
        if _is_fiber_touch_handle(obj, root_name, fiber_id):
            bpy.data.objects.remove(obj, do_unlink=True)


def _is_fiber_touch_handle(obj, root_name, fiber_id):
    valid = obj.get("af_fiber_touch_handle") and obj.get("af_root_name") == root_name
    return bool(valid and obj.get("af_fiber_id") == fiber_id)


def _append_touch_specs(fiber, touch_specs):
    for scp_id, attach_param in tuple(touch_specs or ()):
        _append_touch(fiber, scp_id, attach_param)


def _append_touch(fiber, scp_id, attach_param):
    touch = fiber.mid_touches.add()
    touch.parent_id, touch.attach_param = scp_id, attach_param


def _selected_touch_specs(context, root):
    if _proxy_edit_target(context):
        return _proxy_touch_specs(context, root)
    if _geometry_edit_target(context, root.name):
        return _mesh_touch_specs(context, root)
    return (), ""


def _proxy_touch_specs(context, root):
    picks, error = _selected_proxy_vertices()(context)
    return ((), error) if error else (_proxy_specs_from_picks(root, context.scene, picks), "")


def _proxy_specs_from_picks(root, scene, picks):
    return tuple(spec for spec in (_proxy_spec(root, scene, pick) for pick in tuple(picks or ())) if spec is not None)


def _proxy_edit_target(context):
    obj = getattr(context, "active_object", None)
    return bool(getattr(context, "mode", "") == "EDIT_MESH" and obj and obj.get("af_scp_proxy_view"))


def _geometry_edit_target(context, root_name):
    obj = getattr(context, "active_object", None)
    valid = getattr(context, "mode", "") == "EDIT_MESH" and _single_edit_target(context, obj)
    return bool(valid and _is_geometry_scp_obj()(obj, root_name))


def _single_edit_target(context, obj):
    return len(tuple(getattr(context, "objects_in_mode", ()) or (obj,))) == 1


def _mesh_touch_specs(context, root):
    obj = getattr(context, "active_object", None)
    indices = _selected_mesh_indices(obj)
    return ((), "Select one or more mesh vertices.") if not indices else (_mesh_specs(root, context.scene, obj, indices), "")


def _selected_mesh_indices(obj):
    import bmesh

    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    return _ordered_mesh_indices(bm)


def _ordered_mesh_indices(bm):
    history = _history_mesh_indices(bm)
    seen = set(history)
    return history + [vert.index for vert in bm.verts if vert.select and vert.index not in seen]


def _history_mesh_indices(bm):
    import bmesh

    return [elem.index for elem in bm.select_history if isinstance(elem, bmesh.types.BMVert) and elem.select]


def _mesh_specs(root, scene, obj, indices):
    return tuple(spec for spec in (_mesh_spec(root, scene, obj, index) for index in tuple(indices or ())) if spec is not None)


def _default_touch_specs(context, root):
    scp_id = _touch_parent_id(context, root)
    attach_param = None if not scp_id else _first_attach_param(context.scene, root, scp_id)
    return () if not attach_param else ((scp_id, attach_param),)


def _touch_parent_id(context, root):
    obj = getattr(context, "active_object", None)
    if _is_bound_scp_obj()(obj, root.name):
        return obj.get("af_scp_id", "")
    index = root.af_scp_system.active_scp_index
    scps = root.af_scp_system.scps
    return scps[index].id if 0 <= index < len(scps) else ""


def _first_attach_param(scene, root, scp_id):
    parent_obj = _find_geometry_mesh_scp_obj()(scene, root.name, scp_id)
    point = None if parent_obj is None else parent_obj.matrix_world.translation.copy()
    return None if point is None else _capture_attachment_from_world()(root, scene, scp_id, point)


def _mesh_spec(root, scene, obj, index):
    scp_id = str(obj.get("af_scp_id", "") or "")
    raw = None if not scp_id else _capture_attachment_from_mesh_vertex()(root, scene, scp_id, index)
    return None if raw is None else (scp_id, raw)


def _world_touch_spec(root, scene, scp_id, point):
    sid = str(scp_id or "")
    raw = None if not sid else _capture_attachment_from_world()(root, scene, sid, point)
    return None if raw is None else (sid, raw)


def _proxy_spec(root, scene, pick):
    raw = _capture_attachment_from_proxy_vertex()(root, scene, pick.scp_id, pick.vertex_index, pick.signature)
    return None if raw is None else (pick.scp_id, raw)


def _sync_entity(root, scene, kind, entity_ids, bake=False):
    hints = _dirty_hints_for()(kind, entity_ids)
    _sync_scene()(root=root, scene=scene, dirty_hints=hints, bake=bake)


def _sync_scene():
    try:
        from ...app.runtime_api import sync_scene
    except ImportError:
        from app.runtime_api import sync_scene
    return sync_scene


def _dirty_hints_for():
    try:
        from ...core.deps.dirty_hints import dirty_hints_for
    except ImportError:
        from core.deps.dirty_hints import dirty_hints_for
    return dirty_hints_for


def _fiber_sync():
    try:
        from ...core.visualization.fiber_sync import register_fiber_sync
    except ImportError:
        from core.visualization.fiber_sync import register_fiber_sync
    return register_fiber_sync()


def _request_refinement():
    try:
        from ...core.visualization.fiber_refinement import request_fiber_refinement
    except ImportError:
        from core.visualization.fiber_refinement import request_fiber_refinement
    return request_fiber_refinement


def _find_geometry_mesh_scp_obj():
    try:
        from ...core.scp_runtime.common import find_geometry_mesh_scp_obj
    except ImportError:
        from core.scp_runtime.common import find_geometry_mesh_scp_obj
    return find_geometry_mesh_scp_obj


def _is_bound_scp_obj():
    try:
        from ...core.scp_runtime.common import is_bound_scp_obj
    except ImportError:
        from core.scp_runtime.common import is_bound_scp_obj
    return is_bound_scp_obj


def _selected_proxy_vertices():
    try:
        from ...core.scp_proxy import selected_proxy_vertices
    except ImportError:
        from core.scp_proxy import selected_proxy_vertices
    return selected_proxy_vertices


def _capture_attachment_from_world():
    try:
        from ...core.vcp.attachment_backend import capture_attachment_from_world
    except ImportError:
        from core.vcp.attachment_backend import capture_attachment_from_world
    return capture_attachment_from_world


def _capture_attachment_from_mesh_vertex():
    try:
        from ...core.vcp.attachment_backend import capture_attachment_from_mesh_vertex
    except ImportError:
        from core.vcp.attachment_backend import capture_attachment_from_mesh_vertex
    return capture_attachment_from_mesh_vertex


def _capture_attachment_from_proxy_vertex():
    try:
        from ...core.vcp.attachment_backend import capture_attachment_from_proxy_vertex
    except ImportError:
        from core.vcp.attachment_backend import capture_attachment_from_proxy_vertex
    return capture_attachment_from_proxy_vertex


def _is_geometry_scp_obj():
    try:
        from ...core.scp_runtime.common import is_geometry_scp_obj
    except ImportError:
        from core.scp_runtime.common import is_geometry_scp_obj
    return is_geometry_scp_obj
