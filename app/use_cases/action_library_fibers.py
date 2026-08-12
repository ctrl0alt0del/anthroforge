import bpy

from ..runtime_api import sync_scene
from .results import success

try:
    from ...core.deps.dirty_hints import dirty_hints_for
    from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
except ImportError:
    from core.deps.dirty_hints import dirty_hints_for
    from core.vcp.prop_update_guard import suppress_vcp_prop_updates


def disable_surface_routing_for_all_fibers():
    changes = _disable_file_roots()
    for root, fiber_ids in changes:
        _sync_root_scenes(root, fiber_ids)
    count = sum(len(fiber_ids) for _root, fiber_ids in changes)
    message = f"Disabled surface routing for {count} Fiber(s)." if count else "Surface routing is already disabled for every Fiber."
    return success(message, value=count)


def _disable_file_roots():
    changes = []
    with suppress_vcp_prop_updates():
        for root in _file_roots():
            fiber_ids = _disable_root(root)
            if fiber_ids:
                changes.append((root, fiber_ids))
    return changes


def _file_roots():
    return tuple(obj for obj in bpy.data.objects if obj.get("anthroforge_root") and hasattr(obj, "af_vcp_system"))


def _disable_root(root):
    fibers = tuple(root.af_vcp_system.fibers)
    changed = {str(fiber.id) for fiber in fibers if fiber.use_surface_routing}
    for fiber in fibers:
        if str(fiber.id) in changed:
            fiber.use_surface_routing = False
    return changed


def _sync_root_scenes(root, fiber_ids):
    hints = dirty_hints_for("FIBER", fiber_ids)
    for scene in tuple(getattr(root, "users_scene", ()) or ()):
        sync_scene(root=root, scene=scene, dirty_hints=hints, source="action_library", event_type="UPDATE")
