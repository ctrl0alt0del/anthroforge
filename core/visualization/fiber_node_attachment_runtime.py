"""Apply ordinary SCP-to-Fiber node attachments during propagated updates."""

from ..utils import depsgraph_for_scene
from ..vcp.attachment_backend import attachment_runtime
from ..vcp.fiber_modes import is_loop_fiber
from ..vcp.fiber_node_attachment import (capture_fiber_node_attachments,
                                         resolve_fiber_node_attachments, upgrade_fiber_node_attachments)
from ..vcp.fiber_node_attachment_codec import NODE_ATTACHMENT_VERSION, decode_node_attachments
from ..vcp.runtime_state import (fiber_recompute_status, set_fiber_invalid_reason,
                                 set_fiber_recompute_status)
from .fiber_sync import register_fiber_sync
from .fiber_sync_helpers import persisted_fiber_points
from ..vcp.free_path import fiber_geometry_point_count, is_free


def apply_fiber_node_attachments(root, scene, fiber_ids):
    return _apply_fiber_node_attachments_serial(root, scene, fiber_ids)


def _apply_fiber_node_attachments_serial(root, scene, fiber_ids):
    from ..vcp.attachment_surface import muscle_backed
    from .muscle_fiber_attachment import apply_batch
    fibers = _selected_fibers(root, fiber_ids); handled = {fiber.id for fiber in fibers}
    if not fibers: return handled
    sync = register_fiber_sync(); runtime = attachment_runtime(scene, depsgraph_for_scene(scene))
    muscle_fibers = tuple(f for f in fibers if muscle_backed(f))
    if muscle_fibers: apply_batch(sync, root, scene, muscle_fibers)
    fibers = tuple(f for f in fibers if not muscle_backed(f))
    _apply_scp_batch(sync, root, scene, fibers, runtime)
    sync.refresh_selection(root=root, scene=scene, fiber_ids=handled, sync_handles=True)
    return handled


def _apply_scp_batch(sync, root, scene, fibers, runtime):
    if not fibers: return
    from ..vcp.fiber_node_attachment import _surface_objects
    runtime['node_attachment_objects'] = _surface_objects(scene, root)
    sync.begin_point_batch()
    try:
        for fiber in fibers: _apply_one(sync, root, scene, fiber, runtime)
    finally:
        sync.end_point_batch()


def capture_missing_fiber_node_attachments(root, scene, fiber_ids=None):
    fibers = _selected_fibers(root, fiber_ids); depsgraph = depsgraph_for_scene(scene)
    return {fiber.id for fiber in fibers if _capture_missing_one(root, scene, fiber, depsgraph)}


def _capture_missing_one(root, scene, fiber, depsgraph):
    if is_free(fiber): return False
    if _binding_current(fiber): return False
    from ..vcp.attachment_surface import muscle_backed
    if muscle_backed(fiber): return False
    if _binding_version_matches(fiber, 1): return upgrade_fiber_node_attachments(root, scene, fiber, depsgraph)
    points = persisted_fiber_points(scene, root.name, fiber.id) or ()
    return capture_fiber_node_attachments(root, scene, fiber, points, depsgraph).ok


def capture_committed_fiber_node_attachments(root, scene, fiber, points):
    depsgraph = depsgraph_for_scene(scene)
    return capture_fiber_node_attachments(root, scene, fiber, points, depsgraph).ok


def _selected_fibers(root, fiber_ids):
    wanted = None if fiber_ids is None else set(fiber_ids or ())
    fibers = getattr(root.af_vcp_system, "fibers", ())
    return tuple(row for row in fibers if wanted is None or row.id in wanted)


def _binding_current(fiber):
    payload = decode_node_attachments(getattr(fiber, 'node_attachments_json', ''))
    return bool(payload is not None and payload.version in (1, 2, NODE_ATTACHMENT_VERSION)
                and payload.point_count == fiber_geometry_point_count(fiber) and payload.cyclic == is_loop_fiber(fiber))


def _binding_version_matches(fiber, version):
    payload = decode_node_attachments(getattr(fiber, "node_attachments_json", ""))
    return bool(payload is not None and payload.version == version and payload.point_count == fiber_geometry_point_count(fiber)
                and payload.cyclic == is_loop_fiber(fiber))


def _apply_one(sync, root, scene, fiber, runtime):
    if is_free(fiber):
        from .free_fiber_runtime import update
        return update(root, scene, fiber, runtime=runtime)[0]
    result = resolve_fiber_node_attachments(root, scene, fiber, runtime)
    if not result.ok:
        _attachment_failed(fiber, result.error); return False
    proxy = sync.apply_points(root, scene, fiber, result.points, commit=True)
    if proxy is None:
        _attachment_failed(fiber, "Fiber proxy is unavailable."); return False
    proxy.pop("af_fiber_display_mode", None); _attachment_succeeded(fiber)
    return True


def _attachment_failed(fiber, error):
    set_fiber_invalid_reason(fiber, str(error or "Fiber node attachment failed."))
    set_fiber_recompute_status(fiber, "INVALID_ATTACHMENT")


def _attachment_succeeded(fiber):
    set_fiber_invalid_reason(fiber, "")
    if fiber_recompute_status(fiber) == "INVALID_ATTACHMENT":
        set_fiber_recompute_status(fiber, "UNKNOWN")
