import time

from mathutils import Vector

try:
    from ...core.id_utils import next_prefixed_id
    from ...core.vcp.fiber_modes import is_solved_loop
    from ...core.vcp.runtime_state import (
        fiber_eps_disp,
        fiber_eps_pen,
        fiber_not_converged,
        reset_fiber_runtime,
        set_fiber_recompute_ms,
        set_fiber_recompute_status,
    )
except ImportError:
    from core.id_utils import next_prefixed_id
    from core.vcp.fiber_modes import is_solved_loop
    from core.vcp.runtime_state import (
        fiber_eps_disp,
        fiber_eps_pen,
        fiber_not_converged,
        reset_fiber_runtime,
        set_fiber_recompute_ms,
        set_fiber_recompute_status,
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
    root = root_for_context(context)
    fiber, error = _resolved_fiber(root, fiber_id)
    if fiber is None:
        return failure(error)
    _set_prefer_bake(fiber, True)
    elapsed_ms, converged = _recompute(root, context.scene, fiber, int(max_passes))
    _set_recompute_state(fiber, elapsed_ms, converged)
    return success(_recompute_message(fiber.id, converged, max_passes), _recompute_level(converged), fiber)


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


def add_dependent_loop(context, fiber_id=""):
    root = root_for_context(context)
    fiber, error = _resolved_fiber(root, fiber_id)
    if fiber is None or not is_solved_loop(fiber):
        return failure(error or "Select a solved loop fiber.")
    child = _new_dependent_loop(root, fiber)
    root.af_vcp_system.active_vcp_type, root.af_vcp_system.active_vcp_id = "FIBER", child.id
    _sync_entity(root, context.scene, "FIBER", {fiber.id, child.id}, bake=False)
    return success(value=child)


def add_loop_profile_key(context, fiber_id="", t=0.0):
    root = root_for_context(context)
    fiber, error = _resolved_fiber(root, fiber_id)
    if fiber is None:
        return failure(error)
    key = fiber.loop_profile_keys.add()
    key.t, key.delta_u, key.delta_v = _wrapped_t(t), 0.0, 0.0
    _sync_entity(root, context.scene, "FIBER", {fiber.id}, bake=False)
    return success(value=fiber)


def remove_loop_profile_key(context, fiber_id="", key_index=-1):
    root = root_for_context(context)
    fiber, error = _resolved_fiber(root, fiber_id)
    if fiber is None:
        return failure(error)
    if key_index < 0 or key_index >= len(fiber.loop_profile_keys):
        return failure("Invalid profile key index.")
    fiber.loop_profile_keys.remove(int(key_index))
    _sync_entity(root, context.scene, "FIBER", {fiber.id}, bake=False)
    return success(value=fiber)


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


def _set_recompute_state(fiber, elapsed_ms, converged):
    set_fiber_recompute_ms(fiber, elapsed_ms)
    set_fiber_recompute_status(fiber, "CONVERGED" if converged else "NOT_CONVERGED")


def _recompute(root, scene, fiber, max_passes):
    t0 = time.perf_counter()
    converged = _run_bake_passes(root, scene, fiber, max_passes)
    return (time.perf_counter() - t0) * 1000.0, converged


def _run_bake_passes(root, scene, fiber, max_passes):
    last = None
    for _ in range(_bake_pass_total(fiber, max_passes)):
        _sync_entity(root, scene, "FIBER", {fiber.id}, bake=True)
        if not fiber_not_converged(fiber):
            return True
        state = _fiber_residual_state(fiber)
        if _stalled_bake_state(last, state):
            break
        last = state
    return False


def _fiber_residual_state(fiber):
    return round(float(fiber_eps_disp(fiber)), 9), round(float(fiber_eps_pen(fiber)), 9)


def _bake_pass_total(fiber, max_passes):
    limit = 3 if is_solved_loop(fiber) else int(max_passes)
    return max(1, min(int(max_passes), limit))


def _stalled_bake_state(previous, current, tol=1.0e-9):
    if previous is None:
        return False
    return abs(previous[0] - current[0]) <= tol and abs(previous[1] - current[1]) <= tol


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
    _set_prefer_bake(fiber, False)
    _fiber_sync().clear_solver_cache(fiber.id)
    _sync_entity(root, context.scene, "FIBER", {fiber.id}, bake=False)
    return success(value=fiber)


def _append_touch_specs(fiber, touch_specs):
    for scp_id, attach_param in tuple(touch_specs or ()):
        _append_touch(fiber, scp_id, attach_param)


def _append_touch(fiber, scp_id, attach_param):
    touch = fiber.mid_touches.add()
    touch.parent_id, touch.attach_param = scp_id, attach_param


def _new_dependent_loop(root, fiber):
    child = root.af_vcp_system.fibers.add()
    child.id = next_prefixed_id(root.af_vcp_system.fibers, "FIBER")
    child.name = child.id
    _apply_derived_defaults(child, fiber)
    reset_fiber_runtime(child)
    return child


def _apply_derived_defaults(child, fiber):
    child.topology_mode, child.generation_mode = "LOOP", "DERIVED"
    child.driver_fiber_id, child.node_count = fiber.id, int(fiber.node_count)
    _copy_loop_settings(child, fiber)
    _apply_profile_defaults(child)


def _copy_loop_settings(child, fiber):
    for key in ("thickness", "collision_margin", "damping", "bend_stiffness", "stretch_stiffness", "iterations_interactive", "iterations_bake", "guide_stiffness"):
        setattr(child, key, getattr(fiber, key))


def _apply_profile_defaults(fiber):
    for value in (0.0, 0.25, 0.5, 0.75):
        key = fiber.loop_profile_keys.add()
        key.t, key.delta_u, key.delta_v = value, 0.0, 0.0


def _wrapped_t(value):
    return float(value) % 1.0


def _selected_touch_specs(context, root):
    if _proxy_edit_target(context):
        return _proxy_touch_specs(context)
    if _geometry_edit_target(context, root.name):
        return _mesh_touch_specs(context)
    return (), ""


def _proxy_touch_specs(context):
    picks, error = _selected_proxy_vertices()(context)
    return ((), error) if error else (_proxy_specs_from_picks(picks), "")


def _proxy_specs_from_picks(picks):
    encode = _encode_fiber_vertex_index()
    return tuple((pick.scp_id, encode(pick.vertex_index, pick.signature)) for pick in tuple(picks or ()))


def _proxy_edit_target(context):
    obj = getattr(context, "active_object", None)
    return bool(getattr(context, "mode", "") == "EDIT_MESH" and obj and obj.get("af_scp_proxy_view"))


def _geometry_edit_target(context, root_name):
    obj = getattr(context, "active_object", None)
    valid = getattr(context, "mode", "") == "EDIT_MESH" and _single_edit_target(context, obj)
    return bool(valid and _is_geometry_scp_obj()(obj, root_name))


def _single_edit_target(context, obj):
    return len(tuple(getattr(context, "objects_in_mode", ()) or (obj,))) == 1


def _mesh_touch_specs(context):
    obj = getattr(context, "active_object", None)
    indices = _selected_mesh_indices(obj)
    return ((), "Select one or more mesh vertices.") if not indices else (_mesh_specs(obj, indices), "")


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


def _mesh_specs(obj, indices):
    scp_id = str(obj.get("af_scp_id", "") or "")
    encode = _encode_fiber_anchor()
    return tuple((scp_id, encode(obj.data.vertices[i].co.copy())) for i in tuple(indices or ()) if 0 <= int(i) < len(obj.data.vertices))


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
    if parent_obj is None:
        return None
    point = _nearest_parent_vertex()(parent_obj, parent_obj.matrix_world.translation.copy())
    point = Vector((0.0, 0.0, 0.0)) if point is None else point
    return _encode_fiber_anchor()(point)


def _recompute_message(fiber_id, converged, max_passes):
    return f"Fiber {fiber_id} converged" if converged else f"Fiber {fiber_id} not converged after {max_passes} passes"


def _recompute_level(converged):
    return "INFO" if converged else "WARNING"


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


def _nearest_parent_vertex():
    try:
        from ...core.visualization.fiber_sync_helpers import nearest_parent_mesh_vertex_local_point
    except ImportError:
        from core.visualization.fiber_sync_helpers import nearest_parent_mesh_vertex_local_point
    return nearest_parent_mesh_vertex_local_point


def _encode_fiber_anchor():
    try:
        from ...core.attachment_codec import encode_fiber_mesh_anchor
    except ImportError:
        from core.attachment_codec import encode_fiber_mesh_anchor
    return encode_fiber_mesh_anchor


def _encode_fiber_vertex_index():
    try:
        from ...core.attachment_codec import encode_fiber_vertex_index
    except ImportError:
        from core.attachment_codec import encode_fiber_vertex_index
    return encode_fiber_vertex_index


def _selected_proxy_vertices():
    try:
        from ...core.scp_proxy import selected_proxy_vertices
    except ImportError:
        from core.scp_proxy import selected_proxy_vertices
    return selected_proxy_vertices


def _is_geometry_scp_obj():
    try:
        from ...core.scp_runtime.common import is_geometry_scp_obj
    except ImportError:
        from core.scp_runtime.common import is_geometry_scp_obj
    return is_geometry_scp_obj
