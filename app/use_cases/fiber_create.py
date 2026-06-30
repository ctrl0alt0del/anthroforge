import bpy

from ..queries.root import root_for_context
from .results import failure, success

try:
    from ...core.vcp.runtime_state import reset_fiber_runtime
except ImportError:
    from core.vcp.runtime_state import reset_fiber_runtime

try:
    from ...core.id_utils import next_prefixed_id
except ImportError:
    from core.id_utils import next_prefixed_id


def create_fiber_vcp(context):
    root = root_for_context(context)
    if root is None:
        return failure("No AF_ROOT found.")
    return _create_fiber(context, root, _resolved_inputs(context, root), "Select valid SCP geometry endpoints.")


def create_fiber_from_proxy_vertices(context):
    root = root_for_context(context)
    if root is None:
        return failure("No AF_ROOT found.")
    picks, error = _selected_proxy_vertices()(context)
    if error:
        return failure(error)
    resolved, error = _resolved_proxy_inputs(root, context.scene, picks)
    return _create_fiber(context, root, resolved, error)


def create_loop_fiber_from_selected_vertices(context):
    root = root_for_context(context)
    if root is None:
        return failure("No AF_ROOT found.")
    specs, error = _resolved_loop_specs(context, root)
    if not specs:
        return failure(error or "Select at least three ordered vertices.")
    fiber = _new_loop_fiber(root, specs)
    _activate(root.af_vcp_system, "FIBER", fiber.id)
    _sync_entity(root, context.scene, "FIBER", {fiber.id}, bake=True)
    _finalize_selection(context, root, fiber)
    return success(f"Added {fiber.id}", value=fiber)


def _create_fiber(context, root, resolved, error_message):
    if resolved is None:
        return failure(error_message or "Could not resolve fiber endpoints.")
    fiber = _new_fiber(root, *resolved)
    _activate(root.af_vcp_system, "FIBER", fiber.id)
    _sync_entity(root, context.scene, "FIBER", {fiber.id})
    _finalize_selection(context, root, fiber)
    return success(f"Added {fiber.id}", value=fiber)


def _resolved_inputs(context, root):
    origin_id, insert_id = _endpoint_ids(context)
    if not origin_id or not insert_id:
        return None
    origin_raw = _first_attach_param(context.scene, root, origin_id)
    insert_raw = _first_attach_param(context.scene, root, insert_id)
    return None if origin_raw is None or insert_raw is None else _fiber_spec(origin_id, insert_id, origin_raw, insert_raw)


def _resolved_proxy_inputs(root, scene, picks):
    picks = tuple(picks or ())
    if len(picks) < 2:
        return None, "Select at least two proxy vertices."
    a, b = picks[0], picks[-1]
    a_raw = _proxy_attach(root, scene, a)
    b_raw = _proxy_attach(root, scene, b)
    if a_raw is None or b_raw is None:
        return None, "Could not capture selected proxy endpoints."
    touches, error = _proxy_specs(root, scene, picks[1:-1], "selected proxy mid vertex")
    return (None, error) if error else (_fiber_spec(a.scp_id, b.scp_id, a_raw, b_raw, touches), "")


def _fiber_spec(origin_id, insert_id, origin_raw, insert_raw, touch_specs=()):
    return origin_id, insert_id, origin_raw, insert_raw, tuple(touch_specs or ())


def _proxy_specs(root, scene, picks, label="selected proxy vertex"):
    items = tuple(picks or ())
    specs = tuple(_proxy_spec(root, scene, pick) for pick in items)
    failed = next((pick for pick, spec in zip(items, specs) if spec is None), None)
    return (None, _proxy_spec_error(failed, label)) if failed else (specs, "")


def _proxy_spec_error(pick, label):
    if pick is None:
        return f"Could not capture {label}s."
    return f"Could not capture {label} on {pick.scp_id} (vertex {int(pick.vertex_index)})."


def _resolved_loop_specs(context, root):
    if _proxy_edit_target(context):
        return _proxy_loop_specs(context, root)
    if _geometry_edit_target(context, root.name):
        return _mesh_loop_specs(context, root)
    return None, "Select ordered mesh/proxy vertices in Edit Mode."


def _proxy_loop_specs(context, root):
    picks, error = _selected_proxy_vertices()(context)
    return (None, error) if error else _proxy_specs_from_picks(root, context.scene, picks)


def _proxy_specs_from_picks(root, scene, picks):
    items = tuple(picks or ())
    if len(items) < 3:
        return None, "Select at least three ordered vertices."
    return _proxy_specs(root, scene, items)


def _mesh_loop_specs(context, root):
    obj = getattr(context, "active_object", None)
    indices = _selected_mesh_indices(obj)
    return (None, "Select at least three mesh vertices.") if len(indices) < 3 else (_mesh_specs(root, context.scene, obj, indices), "")


def _endpoint_ids(context):
    origin = getattr(context.scene, "af_new_fiber_origin_obj", None)
    insert = getattr(context.scene, "af_new_fiber_insertion_obj", None)
    if not origin or not insert:
        return None, None
    return origin.get("af_scp_id", ""), insert.get("af_scp_id", "")


def _first_attach_param(scene, root, parent_id):
    return _capture_attachment_from_world()(root, scene, parent_id, scene.cursor.location.copy())


def _new_fiber(root, origin_id, insert_id, origin_raw, insert_raw, touch_specs=()):
    fibers = root.af_vcp_system.fibers
    fiber = fibers.add()
    fiber.id = next_prefixed_id(fibers, "FIBER")
    fiber.name = fiber.id
    fiber.a_parent_id, fiber.a_attach_param = origin_id, origin_raw
    fiber.b_parent_id, fiber.b_attach_param = insert_id, insert_raw
    _apply_touch_specs(fiber, touch_specs)
    _apply_values(fiber, _fiber_defaults())
    reset_fiber_runtime(fiber)
    return fiber


def _new_loop_fiber(root, anchor_specs):
    fiber = _new_fiber(root, "", "", "0.0", "0.0")
    fiber.topology_mode, fiber.generation_mode = "LOOP", "SOLVED"
    fiber.a_parent_id, fiber.a_attach_param = "", ""
    fiber.b_parent_id, fiber.b_attach_param = "", ""
    fiber.driver_fiber_id = ""
    _apply_loop_anchor_specs(fiber, anchor_specs)
    return fiber


def _apply_touch_specs(fiber, touch_specs):
    for parent_id, attach_param in tuple(touch_specs or ()):
        _append_touch(fiber, parent_id, attach_param)


def _append_touch(fiber, parent_id, attach_param):
    touch = fiber.mid_touches.add()
    touch.parent_id, touch.attach_param = parent_id, attach_param


def _apply_loop_anchor_specs(fiber, anchor_specs):
    for parent_id, attach_param in tuple(anchor_specs or ()):
        _append_loop_anchor(fiber, parent_id, attach_param)


def _append_loop_anchor(fiber, parent_id, attach_param):
    anchor = fiber.loop_anchors.add()
    anchor.parent_id, anchor.attach_param = parent_id, attach_param


def _fiber_defaults():
    return {
        "use_warm_start": True,
        "node_count": 64,
        "iterations_interactive": 12,
        "iterations_bake": 180,
        "stretch_stiffness": 0.9,
        "bend_stiffness": 0.02,
        "thickness": 0.01,
    }


def _apply_values(item, values):
    for key, value in values.items():
        setattr(item, key, value)


def _activate(vcp, kind, entity_id):
    vcp.active_vcp_type, vcp.active_vcp_id = str(kind or ""), str(entity_id or "")


def _finalize_selection(context, root, fiber):
    if getattr(context, "mode", "") == "EDIT_MESH" and _active_proxy(context):
        return
    _exit_edit_mode(context)
    proxy = _find_proxy(context.scene, root.name, fiber.id)
    _select_if_found(context, proxy)
    _sync_selection(context.scene, proxy)


def _exit_edit_mode(context):
    if getattr(context, "mode", "") == "EDIT_MESH":
        bpy.ops.object.mode_set(mode="OBJECT")


def _active_proxy(context):
    obj = None if context is None else getattr(context, "active_object", None)
    return bool(obj and obj.get("af_scp_proxy_view"))


def _proxy_edit_target(context):
    obj = getattr(context, "active_object", None)
    return bool(getattr(context, "mode", "") == "EDIT_MESH" and obj and obj.get("af_scp_proxy_view"))


def _geometry_edit_target(context, root_name):
    obj = getattr(context, "active_object", None)
    valid = getattr(context, "mode", "") == "EDIT_MESH" and _single_edit_target(context, obj)
    return bool(valid and _is_geometry_scp_obj()(obj, root_name))


def _single_edit_target(context, obj):
    return len(tuple(getattr(context, "objects_in_mode", ()) or (obj,))) == 1


def _selected_mesh_indices(obj):
    import bmesh

    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    return _ordered_mesh_indices(bm)


def _ordered_mesh_indices(bm):
    history = _history_mesh_indices(bm)
    seen = set(history)
    return history + [vert.index for vert in bm.verts if vert.select and vert.index not in seen]


def _mesh_specs(root, scene, obj, indices):
    return tuple(spec for spec in (_mesh_spec(root, scene, obj, index) for index in tuple(indices or ())) if spec is not None)


def _mesh_spec(root, scene, obj, index):
    scp_id = str(obj.get("af_scp_id", "") or "")
    raw = None if not scp_id else _capture_attachment_from_mesh_vertex()(root, scene, scp_id, index)
    return None if raw is None else (scp_id, raw)


def _proxy_spec(root, scene, pick):
    raw = _proxy_attach(root, scene, pick)
    return None if raw is None else (pick.scp_id, raw)


def _proxy_attach(root, scene, pick):
    return _capture_attachment_from_proxy_vertex()(root, scene, pick.scp_id, pick.vertex_index, pick.signature)


def _history_mesh_indices(bm):
    import bmesh

    return [elem.index for elem in bm.select_history if isinstance(elem, bmesh.types.BMVert) and elem.select]


def _select_if_found(context, obj):
    if obj is None:
        return
    for item in getattr(context, "selected_objects", ()):
        item.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _sync_entity(root, scene, kind, entity_ids, bake=False):
    hints = _dirty_hints_for()(kind, entity_ids)
    _sync_scene()(root=root, scene=scene, dirty_hints=hints, bake=bake)


def _sync_selection(scene, active_object):
    if active_object is None:
        return
    _notify_selection_changed()(scene, force=True, active_object=active_object)


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


def _find_geometry_mesh_scp_obj():
    try:
        from ...core.scp_runtime.common import find_geometry_mesh_scp_obj
    except ImportError:
        from core.scp_runtime.common import find_geometry_mesh_scp_obj
    return find_geometry_mesh_scp_obj


def _find_proxy(scene, root_name, fiber_id):
    for obj in getattr(scene, "objects", ()):
        if obj.get("af_fiber_proxy") and obj.get("af_root_name") == root_name and obj.get("af_fiber_id") == fiber_id:
            return obj
    return None


def _is_geometry_scp_obj():
    try:
        from ...core.scp_runtime.common import is_geometry_scp_obj
    except ImportError:
        from core.scp_runtime.common import is_geometry_scp_obj
    return is_geometry_scp_obj


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


def _notify_selection_changed():
    try:
        from ...core.visualization.control_runtime import notify_selection_changed
    except ImportError:
        from core.visualization.control_runtime import notify_selection_changed
    return notify_selection_changed
