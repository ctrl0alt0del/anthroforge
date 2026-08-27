import bpy
from bpy.app.handlers import persistent

from ..deps.runtime_context_build import clear_runtime_context_cache
from ..utils import clear_geometry_generations, clear_scene_cache, note_geometry_updates, scene_for_id
from ..vcp.fiber_collision import clear_collider_generations, note_collider_updates
from ..vcp.fiber_solver_v2 import clear_factor_cache
from ..vcp.fiber_v2_runtime import clear_v2_runtime_capture_cache
from ..vcp.v2.production import clear_v2_production_caches
from ..vcp.v3.production import clear_v3_caches


def invalidate_fiber_caches(scene=None, root=None, fiber_ids=None):
    scene = scene or _root_scene(root)
    ids = _normalized_ids(fiber_ids)
    _cancel_refinements(scene, ids)
    _clear_solver_cache(ids)
    clear_factor_cache()
    clear_v2_runtime_capture_cache() if ids is None else None
    clear_v2_production_caches() if ids is None else None
    clear_v3_caches() if ids is None else None
    clear_runtime_context_cache(root)
    clear_scene_cache(scene)
    clear_collider_generations() if ids is None else None
    clear_geometry_generations() if ids is None else None


def _root_scene(root):
    return None if root is None else scene_for_id(root)


def _normalized_ids(values):
    if values is None:
        return None
    values = (values,) if isinstance(values, str) else tuple(values)
    return tuple(str(value) for value in values if str(value or ""))


def _cancel_refinements(scene, fiber_ids):
    from .fiber_refinement import cancel_fiber_refinement, shutdown_fiber_refinements
    if fiber_ids is None:
        shutdown_fiber_refinements(mark_unknown=False)
    elif scene is not None:
        for fiber_id in fiber_ids:
            cancel_fiber_refinement(scene, fiber_id, mark_unknown=False)


def _clear_solver_cache(fiber_ids):
    from . import fiber_sync
    sync = fiber_sync._FIBER_SYNC
    if sync is None:
        return
    if fiber_ids is None:
        sync.clear_solver_cache()
    else:
        for fiber_id in fiber_ids:
            sync.clear_solver_cache(fiber_id)


@persistent
def _on_lifecycle_event(_dummy):
    invalidate_fiber_caches()


@persistent
def _on_depsgraph_update(_scene, depsgraph):
    note_geometry_updates(depsgraph)
    note_collider_updates(depsgraph)


def _handler_lists():
    handlers = bpy.app.handlers
    names = "load_pre", "undo_pre", "redo_pre", "undo_post", "redo_post"
    return tuple(getattr(handlers, name) for name in names if hasattr(handlers, name))


def register_fiber_cache_lifecycle():
    for handlers in _handler_lists():
        if _on_lifecycle_event not in handlers:
            handlers.append(_on_lifecycle_event)
    handlers = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph_update not in handlers:
        handlers.append(_on_depsgraph_update)


def unregister_fiber_cache_lifecycle():
    invalidate_fiber_caches()
    for handlers in _handler_lists():
        if _on_lifecycle_event in handlers:
            handlers.remove(_on_lifecycle_event)
    handlers = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph_update in handlers:
        handlers.remove(_on_depsgraph_update)
