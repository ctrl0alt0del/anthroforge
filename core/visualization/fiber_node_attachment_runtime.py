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


def apply_fiber_node_attachments(root, scene, fiber_ids):
    return _apply_fiber_node_attachments_serial(root, scene, fiber_ids)


def _apply_fiber_node_attachments_serial(root, scene, fiber_ids):
    fibers = _selected_fibers(root, fiber_ids); handled = {fiber.id for fiber in fibers}
    if not fibers: return handled
    sync = register_fiber_sync(); runtime = attachment_runtime(scene, depsgraph_for_scene(scene))
    from ..vcp.fiber_node_attachment import _surface_objects
    runtime['node_attachment_objects'] = _surface_objects(scene, root)
    sync.begin_point_batch()
    try:
        for fiber in fibers: _apply_one(sync, root, scene, fiber, runtime)
    finally:
        sync.end_point_batch()
    sync.refresh_selection(root=root, scene=scene, fiber_ids=handled, sync_handles=True)
    return handled


def capture_missing_fiber_node_attachments(root, scene, fiber_ids=None):
    fibers = _selected_fibers(root, fiber_ids); depsgraph = depsgraph_for_scene(scene)
    return {fiber.id for fiber in fibers if _capture_missing_one(root, scene, fiber, depsgraph)}


def _capture_missing_one(root, scene, fiber, depsgraph):
    if _binding_current(fiber): return False
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
    return _binding_version_matches(fiber, NODE_ATTACHMENT_VERSION)


def _binding_version_matches(fiber, version):
    payload = decode_node_attachments(getattr(fiber, "node_attachments_json", ""))
    return bool(payload is not None and payload.version == version and payload.point_count == int(fiber.node_count)
                and payload.cyclic == is_loop_fiber(fiber))


def _apply_one(sync, root, scene, fiber, runtime):
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
