import json

try:
    from ...core.vcp.runtime_state import (
        fiber_active_colliders,
        fiber_invalid_reason,
        fiber_not_converged,
        fiber_planner_ms,
        fiber_recompute_ms,
        fiber_recompute_status,
        fiber_refine_ms,
        fiber_eps_disp,
        fiber_eps_pen,
        fiber_route_mode,
        reset_fiber_runtime,
        set_fiber_active_colliders,
        set_fiber_eps_disp,
        set_fiber_eps_pen,
        set_fiber_invalid_reason,
        set_fiber_not_converged,
        set_fiber_planner_ms,
        set_fiber_recompute_ms,
        set_fiber_recompute_status,
        set_fiber_refine_ms,
        set_fiber_route_mode,
    )
    from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
except ImportError:
    from core.vcp.runtime_state import (
        fiber_active_colliders,
        fiber_invalid_reason,
        fiber_not_converged,
        fiber_planner_ms,
        fiber_recompute_ms,
        fiber_recompute_status,
        fiber_refine_ms,
        fiber_eps_disp,
        fiber_eps_pen,
        fiber_route_mode,
        reset_fiber_runtime,
        set_fiber_active_colliders,
        set_fiber_eps_disp,
        set_fiber_eps_pen,
        set_fiber_invalid_reason,
        set_fiber_not_converged,
        set_fiber_planner_ms,
        set_fiber_recompute_ms,
        set_fiber_recompute_status,
        set_fiber_refine_ms,
        set_fiber_route_mode,
    )
    from core.vcp.prop_update_guard import suppress_vcp_prop_updates
from ..queries.root import root_for_context
from .results import failure, success


def clear_fiber_warm_start(context, fiber_id=""):
    root = root_for_context(context)
    fiber, error = _resolved_fiber(root, fiber_id)
    if fiber is None:
        return failure(error)
    _fiber_sync().clear_solver_cache(fiber.id)
    _clear_v3_warm(context, root, fiber)
    _reset_fiber_stats(fiber)
    return success(f"Warm-start cache cleared for {fiber.id}", value=fiber)


def _clear_v3_warm(context, root, fiber):
    try:
        from ...core.vcp.fiber_v2_runtime import clear_v3_runtime_warm_cache
    except ImportError:
        from core.vcp.fiber_v2_runtime import clear_v3_runtime_warm_cache
    clear_v3_runtime_warm_cache(context.scene, root, {fiber.id})


def recompute_fiber(context, fiber_id="", max_passes=12):
    _ = max_passes
    root = root_for_context(context)
    fiber, error = _resolved_fiber(root, fiber_id)
    if fiber is None:
        return failure(error)
    request = _request_refinement()(root, context.scene, fiber, show_preview=True)
    if not request.ok:
        return failure(request.error or _invalid_message(fiber))
    return success(f"Refining {fiber.id} in the background", value=fiber)


def restore_legacy_fiber(context, fiber_id=""):
    root = root_for_context(context)
    fiber, error = _resolved_fiber(root, fiber_id)
    if fiber is not None and getattr(fiber, 'behavior_mode', 'CONTROLLED') == 'FREE': return failure('Switch to Controlled before restoring a solver result.')
    points = None if fiber is None else _decoded_points(fiber.legacy_points_json)
    if fiber is None or not points:
        return failure(error or "No legacy Fiber shape is available.")
    _restore_legacy_state(fiber)
    _clear_v3_warm(context, root, fiber)
    proxy = _fiber_sync().apply_points(root, context.scene, fiber, points, commit=True)
    _capture_legacy_node_attachments(root, context.scene, fiber, points)
    _write_legacy_provenance(proxy)
    return success("Legacy Fiber shape restored.", value=proxy)


def _save_legacy_snapshot(root, scene, fiber):
    persisted_fiber_points = _persisted_fiber_points()
    points = persisted_fiber_points(scene, root.name, fiber.id) or ()
    fiber.legacy_points_json = json.dumps([list(point) for point in points])
    fiber.legacy_diagnostics_json = json.dumps(_legacy_diagnostics(fiber))
    fiber.legacy_status = fiber_recompute_status(fiber)
    fiber.legacy_eps_disp, fiber.legacy_eps_pen = fiber_eps_disp(fiber), fiber_eps_pen(fiber)


def _capture_legacy_node_attachments(root, scene, fiber, points):
    try: from ...core.visualization.fiber_node_attachment_runtime import capture_committed_fiber_node_attachments
    except ImportError: from core.visualization.fiber_node_attachment_runtime import capture_committed_fiber_node_attachments
    return capture_committed_fiber_node_attachments(root, scene, fiber, points)


def _legacy_diagnostics(fiber):
    return {"status": fiber_recompute_status(fiber), "eps_disp": fiber_eps_disp(fiber),
            "eps_pen": fiber_eps_pen(fiber), "route": fiber_route_mode(fiber),
            "planner_ms": fiber_planner_ms(fiber), "refine_ms": fiber_refine_ms(fiber),
            "recompute_ms": fiber_recompute_ms(fiber),
            "active_colliders": fiber_active_colliders(fiber),
            "invalid_reason": fiber_invalid_reason(fiber),
            "not_converged": fiber_not_converged(fiber)}


def _cancel_v2_migration(fiber):
    try:
        from ...core.visualization.fiber_engine_migration import clear_engine_migration
    except ImportError:
        from core.visualization.fiber_engine_migration import clear_engine_migration
    clear_engine_migration(fiber)


def _write_legacy_provenance(proxy):
    try:
        from ...core.vcp.fiber_engine_registry import V1_PRODUCTION_VERSION
        from ...core.vcp.fiber_engine_selection import resolve_fiber_engine
        from ...core.visualization.fiber_engine_migration import write_engine_provenance
    except ImportError:
        from core.vcp.fiber_engine_registry import V1_PRODUCTION_VERSION
        from core.vcp.fiber_engine_selection import resolve_fiber_engine
        from core.visualization.fiber_engine_migration import write_engine_provenance
    write_engine_provenance(proxy, resolve_fiber_engine("V1"), V1_PRODUCTION_VERSION)


def _restore_legacy_state(fiber):
    with suppress_vcp_prop_updates():
        fiber.solver_version = 1
    _cancel_v2_migration(fiber)
    _restore_legacy_diagnostics(fiber)
    _fiber_sync().clear_solver_cache(fiber.id)


def _restore_legacy_diagnostics(fiber):
    data = _decoded_mapping(fiber.legacy_diagnostics_json)
    set_fiber_recompute_status(fiber, data.get("status", fiber.legacy_status or "UNKNOWN"))
    set_fiber_eps_disp(fiber, data.get("eps_disp", fiber.legacy_eps_disp))
    set_fiber_eps_pen(fiber, data.get("eps_pen", fiber.legacy_eps_pen))
    _restore_legacy_detail(fiber, data)


def _restore_legacy_detail(fiber, data):
    set_fiber_route_mode(fiber, data.get("route", "LOCAL_FALLBACK"))
    set_fiber_planner_ms(fiber, data.get("planner_ms", 0.0))
    set_fiber_refine_ms(fiber, data.get("refine_ms", 0.0))
    set_fiber_recompute_ms(fiber, data.get("recompute_ms", 0.0))
    set_fiber_active_colliders(fiber, data.get("active_colliders", 0))
    set_fiber_invalid_reason(fiber, data.get("invalid_reason", ""))
    set_fiber_not_converged(fiber, data.get("not_converged", False))


def _decoded_points(raw):
    Vector = _vector_type()
    try:
        return [Vector(tuple(float(value) for value in row[:3])) for row in json.loads(str(raw or ""))]
    except Exception:
        return None


def _vector_type():
    try:
        from mathutils import Vector
        return Vector
    except ImportError:
        return lambda values: tuple(values)


def _decoded_mapping(raw):
    try:
        value = json.loads(str(raw or ""))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _persisted_fiber_points():
    try:
        from ...core.visualization.fiber_sync_helpers import persisted_fiber_points
    except ImportError:
        from core.visualization.fiber_sync_helpers import persisted_fiber_points
    return persisted_fiber_points


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
    spec = _world_touch_spec(root, context.scene, scp_id, point, float(getattr(fiber, 'collision_radius', .002)))
    if spec is None:
        return failure("Click a valid SCP geometry surface.")
    return _append_touch_result(context, root, fiber, (spec,))


def remove_fiber_touch_point(context, fiber_id="", touch_index=-1):
    root = root_for_context(context)
    fiber, error = _resolved_fiber(root, fiber_id)
    index = int(touch_index)
    if fiber is None:
        return failure(error)
    if getattr(fiber, 'behavior_mode', 'CONTROLLED') == 'FREE': return failure('Free path structural anchors must retain their tagged order.')
    if index < 0 or index >= len(fiber.mid_touches) or (fiber.id, index+1) in _branch_protected(root):
        return failure("Invalid touch index.")
    fiber.mid_touches.remove(index)
    return _removed_touch(context, root, fiber)


def _removed_touch(context, root, fiber):
    _retire_warning_pins(root, fiber)
    _set_prefer_bake(fiber, False)
    _fiber_sync().clear_solver_cache(fiber.id)
    _clear_v3_warm(context, root, fiber)
    _sync_entity(root, context.scene, "FIBER", {fiber.id}, bake=False)
    return success(value=fiber)


def move_fiber_touch_point(context, fiber_id="", touch_index=-1, direction=0):
    root = root_for_context(context)
    fiber, error = _resolved_fiber(root, fiber_id)
    index, target = int(touch_index), int(touch_index) + int(direction)
    if fiber is None:
        return failure(error)
    if getattr(fiber, 'behavior_mode', 'CONTROLLED') == 'FREE': return failure('Free path structural anchors must retain their tagged order.')
    if not _valid_touch_move(fiber, index, target) or not _routing_touch_move(root, fiber, index, target):
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
    radius = float(getattr(fiber, 'collision_radius', .002))
    touch_specs, error = _selected_touch_specs(context, root, radius)
    if error:
        return None, error
    touch_specs = touch_specs or _default_touch_specs(context, root, radius)
    return (None, "Select a fiber and a valid SCP geometry object.") if not touch_specs else ((fiber, touch_specs), "")


def _resolved_touch(context, root, fiber_id=""):
    resolved, _error = _resolved_touches(context, root, fiber_id)
    if resolved is None or len(resolved[1]) != 1:
        return None
    fiber, touch_specs = resolved
    return fiber, touch_specs[0][0], touch_specs[0][1]


def _append_touch_result(context, root, fiber, touch_specs):
    if getattr(fiber, 'behavior_mode', 'CONTROLLED') == 'FREE': return failure('Edit Free path samples without adding routing anchors.')
    try: from ...adapters.free_fiber_transaction import run
    except ImportError: from adapters.free_fiber_transaction import run
    try: return run(root, context.scene, lambda: _append_acyclic_touch(context, root, fiber, touch_specs))
    except ValueError as exc: return failure(str(exc))


def _append_acyclic_touch(context, root, fiber, specs):
    try: from ...core.deps.surface_dependencies import require_acyclic
    except ImportError: from core.deps.surface_dependencies import require_acyclic
    _append_touch_specs(fiber, specs)
    require_acyclic(root)
    return _touch_order_changed(context, root, fiber)


def _touch_order_changed(context, root, fiber):
    _retire_warning_pins(root, fiber)
    _set_prefer_bake(fiber, False)
    _fiber_sync().clear_solver_cache(fiber.id)
    _clear_v3_warm(context, root, fiber)
    _sync_entity(root, context.scene, "FIBER", {fiber.id}, bake=False)
    return success(value=fiber)


def _retire_warning_pins(root, fiber):
    try:
        from ...core.visualization.warning_runtime import structural_change
    except ImportError:
        from core.visualization.warning_runtime import structural_change
    structural_change(root, {fiber.id})


def _valid_touch_move(fiber, index, target):
    count = len(fiber.mid_touches)
    return 0 <= index < count and 0 <= target < count and index != target


def _routing_touch_move(root, fiber, index, target):
    protected = {i for key, i in _branch_protected(root) if key == fiber.id}
    if index+1 in protected:
        return False
    surfaces = getattr(root.af_vcp_system, 'fiber_surfaces', ())
    if not protected and not any(c.boundary_fiber_id == fiber.id for s in surfaces for c in s.branches):
        return True
    keys = [fiber.a_point_id, *(p.point_id for p in fiber.mid_touches), fiber.b_point_id]
    if not _branch_touch_order(root, fiber.id, keys):
        return False
    before = [keys[i] for i in sorted(protected)]
    keys.insert(target+1, keys.pop(index+1))
    return before == [key for key in keys if key in before] and _branch_touch_order(root, fiber.id, keys)


def _branch_touch_order(root, fiber_id, keys):
    intervals = []
    for surface in root.af_vcp_system.fiber_surfaces:
        for connection in surface.branches:
            if connection.boundary_fiber_id != fiber_id:
                continue
            roots = [ref.point_id for ref in connection.roots]
            if len(roots) < 2 or len(set(roots)) != len(roots) or any(keys.count(key) != 1 for key in roots):
                return False
            positions = [keys.index(key) for key in roots]
            if positions != sorted(positions) or positions[0] == 0 or positions[-1] == len(keys)-1:
                return False
            intervals.append((positions[0], positions[-1]))
    intervals.sort()
    return all(a[1] < b[0] for a, b in zip(intervals, intervals[1:]))


def _remove_fiber_touch_handles(scene, root_name, fiber_id):
    import bpy

    for obj in tuple(getattr(scene, "objects", ()) or ()):
        if _is_fiber_touch_handle(obj, root_name, fiber_id):
            bpy.data.objects.remove(obj, do_unlink=True)


def _is_fiber_touch_handle(obj, root_name, fiber_id):
    valid = obj.get("af_fiber_touch_handle") and obj.get("af_root_name") == root_name
    return bool(valid and obj.get("af_fiber_id") == fiber_id)


def _append_touch_specs(fiber, touch_specs):
    with suppress_vcp_prop_updates():
        for scp_id, attach_param in tuple(touch_specs or ()):
            _append_touch(fiber, scp_id, attach_param)


def _append_touch(fiber, scp_id, attach_param):
    touch = fiber.mid_touches.add()
    touch.parent_id, touch.attach_param = scp_id, attach_param


def _selected_touch_specs(context, root, radius=.002):
    if _proxy_edit_target(context):
        return _proxy_touch_specs(context, root, radius)
    if _geometry_edit_target(context, root.name):
        return _mesh_touch_specs(context, root, radius)
    return (), ""


def _proxy_touch_specs(context, root, radius=.002):
    picks, error = _selected_proxy_vertices()(context)
    if error: return (), error
    specs = _proxy_specs_from_picks(root, context.scene, picks, radius)
    return _complete_touch_selection(specs, len(picks))


def _proxy_specs_from_picks(root, scene, picks, radius=.002):
    return tuple(spec for spec in (_proxy_spec(root, scene, pick, radius) for pick in tuple(picks or ())) if spec is not None)


def _proxy_edit_target(context):
    obj = getattr(context, "active_object", None)
    return bool(getattr(context, "mode", "") == "EDIT_MESH" and obj and obj.get("af_scp_proxy_view"))


def _geometry_edit_target(context, root_name):
    try: from ...core.vcp.surface_reference import key, from_object
    except ImportError: from core.vcp.surface_reference import key, from_object
    obj = getattr(context, "active_object", None)
    valid = getattr(context, "mode", "") == "EDIT_MESH" and _single_edit_target(context, obj)
    return bool(valid and obj and obj.get('af_root_name') == root_name and key(from_object(obj)))


def _single_edit_target(context, obj):
    return len(tuple(getattr(context, "objects_in_mode", ()) or (obj,))) == 1


def _mesh_touch_specs(context, root, radius=.002):
    obj = getattr(context, "active_object", None)
    indices = _selected_mesh_indices(obj)
    if not indices: return (), "Select one or more mesh vertices."
    return _complete_touch_selection(_mesh_specs(root, context.scene, obj, indices, radius), len(indices))


def _complete_touch_selection(specs, count):
    if len(specs) != count: return (), "No usable collision-clear pin was found for every selected vertex."
    return specs, ""


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


def _mesh_specs(root, scene, obj, indices, radius=.002):
    return tuple(spec for spec in (_mesh_spec(root, scene, obj, index, radius) for index in tuple(indices or ())) if spec is not None)


def _default_touch_specs(context, root, radius=.002):
    scp_id = _touch_parent_id(context, root)
    attach_param = None if not scp_id else _first_attach_param(context.scene, root, scp_id, radius)
    return () if not attach_param else ((scp_id, attach_param),)


def _touch_parent_id(context, root):
    try: from ...core.vcp.surface_reference import key, from_object
    except ImportError: from core.vcp.surface_reference import key, from_object
    obj = getattr(context, "active_object", None)
    if obj and obj.get('af_root_name') == root.name and key(from_object(obj)): return key(from_object(obj))
    if _is_bound_scp_obj()(obj, root.name):
        return obj.get("af_scp_id", "")
    index = root.af_scp_system.active_scp_index
    scps = root.af_scp_system.scps
    return scps[index].id if 0 <= index < len(scps) else ""


def _first_attach_param(scene, root, scp_id, radius=.002):
    try: from ...core.vcp.attachment_backend import _parent_mesh
    except ImportError: from core.vcp.attachment_backend import _parent_mesh
    parent_obj = _parent_mesh(root, scene, scp_id)
    point = None if parent_obj is None else parent_obj.matrix_world.translation.copy()
    return None if point is None else _capture_attachment_from_world()(root, scene, scp_id, point, radius=radius)


def _mesh_spec(root, scene, obj, index, radius=.002):
    try: from ...core.vcp.surface_reference import key, from_object
    except ImportError: from core.vcp.surface_reference import key, from_object
    scp_id = key(from_object(obj))
    raw = None if not scp_id else _capture_attachment_from_mesh_vertex()(root, scene, scp_id, index, radius=radius)
    return None if raw is None else (scp_id, raw)


def _world_touch_spec(root, scene, scp_id, point, radius=.002):
    try: from ...core.vcp.surface_reference import key
    except ImportError: from core.vcp.surface_reference import key
    sid = key(scp_id)
    raw = None if not sid else _capture_attachment_from_world()(root, scene, sid, point, radius=radius)
    return None if raw is None else (sid, raw)


def _proxy_spec(root, scene, pick, radius=.002):
    raw = _capture_attachment_from_proxy_vertex()(root, scene, pick.scp_id, pick.vertex_index, pick.signature, radius=radius)
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
        from ...core.vcp.fiber_pin_snapping import capture_attachment_from_world
    except ImportError:
        from core.vcp.fiber_pin_snapping import capture_attachment_from_world
    return capture_attachment_from_world


def _capture_attachment_from_mesh_vertex():
    try:
        from ...core.vcp.fiber_pin_snapping import capture_attachment_from_mesh_vertex
    except ImportError:
        from core.vcp.fiber_pin_snapping import capture_attachment_from_mesh_vertex
    return capture_attachment_from_mesh_vertex


def _capture_attachment_from_proxy_vertex():
    try:
        from ...core.vcp.fiber_pin_snapping import capture_attachment_from_proxy_vertex
    except ImportError:
        from core.vcp.fiber_pin_snapping import capture_attachment_from_proxy_vertex
    return capture_attachment_from_proxy_vertex


def _is_geometry_scp_obj():
    try:
        from ...core.scp_runtime.common import is_geometry_scp_obj
    except ImportError:
        from core.scp_runtime.common import is_geometry_scp_obj
    return is_geometry_scp_obj


def _branch_protected(root):
    surfaces = getattr(root.af_vcp_system, 'fiber_surfaces', ())
    if not any(getattr(s, 'branches', ()) for s in surfaces):
        return set()
    from .muscle_branch import protected_references
    return protected_references(root)
