from dataclasses import dataclass

import bpy

from ..queries.root import root_for_context
from ..queries.scp import scp_label
from .fiber_create import _activate, _invalidate_fiber_runtime, _new_fiber
from .results import failure, success

try:
    from ...core.scp_runtime.viewport_picker import pick_candidates
    from ...core.vcp.attachment_backend import attachment_runtime
    from ...core.vcp.fiber_pin_snapping import capture_attachment_from_world
    from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
    from ...core.visualization.fiber_refinement import request_fiber_refinement
except ImportError:
    from core.scp_runtime.viewport_picker import pick_candidates
    from core.vcp.attachment_backend import attachment_runtime
    from core.vcp.fiber_pin_snapping import capture_attachment_from_world
    from core.vcp.prop_update_guard import suppress_vcp_prop_updates
    from core.visualization.fiber_refinement import request_fiber_refinement


@dataclass(frozen=True)
class QuickFiberPoint:
    scp_id: str
    attach_param: str
    attach_world: object
    visual_world: object
    label: str


@dataclass(frozen=True)
class QuickFiberCommit:
    fiber: object
    proxy: object


def quick_fiber_context_error(context):
    root = root_for_context(context)
    if root is None:
        return "No AF_ROOT found."
    area = None if context is None else getattr(context, "area", None)
    if area is None or area.type != "VIEW_3D":
        return "Run Quick Fiber from a 3D View."
    if not pick_candidates(context, root):
        return "No visible SCP geometry is available for surface picking."
    return ""


def capture_quick_fiber_point(context, hit):
    root = root_for_context(context)
    if root is None or hit is None:
        return None, "Click a valid SCP geometry surface."
    scp_id, attach_world, visual_world = hit
    runtime = attachment_runtime(context.scene)
    raw = capture_attachment_from_world(root, context.scene, scp_id, attach_world, runtime)
    if raw is None:
        return None, "No collision-clear surface attachment with a usable exit was found on this SCP."
    snapped = runtime.get('pin_snap_last_result')
    if snapped is not None: attach_world, visual_world = _snapped_preview(snapped, attach_world, visual_world)
    point = QuickFiberPoint(scp_id, raw, attach_world.copy(), visual_world.copy(), scp_label(root, scp_id))
    return point, ""


def _snapped_preview(result, attach_world, visual_world):
    from mathutils import Vector
    surface = Vector(result.surface)
    return surface, visual_world + surface - attach_world


def commit_quick_fiber(context, points):
    root = root_for_context(context)
    values = tuple(points or ())
    if root is None or len(values) < 2:
        return failure("Quick Fiber requires an origin and insertion.")
    fiber = _create_fiber(root, values)
    request = request_fiber_refinement(
        root, context.scene, fiber, show_preview=True, quality="INTERACTIVE")
    if not request.ok or request.proxy is None:
        _rollback_fiber(root, context.scene, fiber.id)
        return failure(request.error or "Quick Fiber could not create its preview route.")
    _activate(root.af_vcp_system, "FIBER", fiber.id)
    _select_proxy(context, request.proxy)
    return success(f"Created {fiber.id}", value=QuickFiberCommit(fiber, request.proxy))


def _create_fiber(root, points):
    origin, insertion = points[0], points[-1]
    touches = tuple((point.scp_id, point.attach_param) for point in points[1:-1])
    with suppress_vcp_prop_updates():
        fiber = _new_fiber(root, origin.scp_id, insertion.scp_id,
                           origin.attach_param, insertion.attach_param, touches)
        fiber.use_segment_collisions = True
    return fiber


def _rollback_fiber(root, scene, fiber_id):
    for obj in tuple(scene.objects):
        if _fiber_object(obj, root.name, fiber_id):
            bpy.data.objects.remove(obj, do_unlink=True)
    fibers = root.af_vcp_system.fibers
    index = next((i for i, item in enumerate(fibers) if item.id == fiber_id), -1)
    if index >= 0:
        fibers.remove(index)
    _invalidate_fiber_runtime(root, fiber_id)


def _fiber_object(obj, root_name, fiber_id):
    same = obj.get("af_root_name") == root_name and obj.get("af_fiber_id") == fiber_id
    return bool(same and (obj.get("af_fiber_proxy") or obj.get("af_fiber_endpoint_handle") or
                          obj.get("af_fiber_touch_handle") or obj.get("af_fiber_loop_anchor_handle")))


def _select_proxy(context, proxy):
    for obj in tuple(getattr(context, "selected_objects", ()) or ()):
        obj.select_set(False)
    proxy.select_set(True)
    context.view_layer.objects.active = proxy
    _notify_selection()(context.scene, force=True, active_object=proxy)


def _notify_selection():
    try:
        from ...core.visualization.control_runtime import notify_selection_changed
    except ImportError:
        from core.visualization.control_runtime import notify_selection_changed
    return notify_selection_changed
