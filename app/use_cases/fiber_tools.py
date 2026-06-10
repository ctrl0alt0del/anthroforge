import time

from mathutils import Vector

try:
    from ...core.vcp.runtime_state import (
        fiber_not_converged,
        reset_fiber_runtime,
        set_fiber_recompute_ms,
        set_fiber_recompute_status,
    )
except ImportError:
    from core.vcp.runtime_state import (
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


def recompute_fiber(context, fiber_id="", max_passes=60):
    root = root_for_context(context)
    fiber, error = _resolved_fiber(root, fiber_id)
    if fiber is None:
        return failure(error)
    elapsed_ms, converged = _recompute(root, context.scene, fiber, int(max_passes))
    _set_prefer_bake(fiber, True)
    _set_recompute_state(fiber, elapsed_ms, converged)
    return success(_recompute_message(fiber.id, converged, max_passes), _recompute_level(converged), fiber)


def add_fiber_touch_point(context, fiber_id=""):
    root = root_for_context(context)
    resolved = _resolved_touch(context, root, fiber_id)
    if resolved is None:
        return failure("Select a fiber and a valid SCP geometry object.")
    fiber, scp_id, attach_param = resolved
    touch = fiber.mid_touches.add()
    touch.parent_id, touch.attach_param = scp_id, attach_param
    _set_prefer_bake(fiber, False)
    _fiber_sync().clear_solver_cache(fiber.id)
    _sync_entity(root, context.scene, "FIBER", {fiber.id}, bake=False)
    return success(value=fiber)


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
    for _ in range(max_passes):
        _sync_entity(root, scene, "FIBER", {fiber.id}, bake=True)
        if not fiber_not_converged(fiber):
            return True
    return False


def _resolved_touch(context, root, fiber_id):
    fiber, _error = _resolved_fiber(root, fiber_id)
    scp_id = _touch_parent_id(context, root)
    if fiber is None or not scp_id:
        return None
    attach_param = _first_attach_param(context.scene, root, scp_id)
    return None if not attach_param else (fiber, scp_id, attach_param)


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
