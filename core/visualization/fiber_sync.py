import bpy

from ..vcp.fiber_modes import is_loop_fiber
from ..vcp.fiber_solver import FiberSolver
from .fiber_sync_helpers import (
    get_vis_collection,
    find_fiber_proxy,
    find_endpoint_handle,
    find_touch_handle,
    create_endpoint_handle,
    create_touch_handle,
    set_fiber_color,
    create_fiber_proxy,
    update_curve_points,
    get_scp_proxy,
    endpoint_world,
    nearest_param,
    nearest_parent_mesh_vertex_local_point,
    world_units_per_pixel,
)
from .fiber_sync_runtime import (
    sync_handles as _sync_handles_runtime,
    apply_selection_highlight as _apply_selection_highlight_runtime,
    refresh_selection as _refresh_selection_runtime,
    sync_root_to_scene as _sync_root_to_scene_runtime,
    on_depsgraph_update as _on_depsgraph_update_runtime,
)

DEFAULT_FIBER_COLOR = (0.85, 0.55, 0.20, 1.0)
SELECTED_FIBER_COLOR = (1.0, 0.0, 0.0, 1.0)


class FiberSceneSync:
    def __init__(self, collection_name="AF_VCP_VIS"):
        self.collection_name = collection_name
        self._solver = FiberSolver(surface_offset=0.002)
        self._syncing = False
        self.default_fiber_color = DEFAULT_FIBER_COLOR
        self.selected_fiber_color = SELECTED_FIBER_COLOR

    def clear_solver_cache(self, fiber_id=None):
        self._solver.clear_cache(fiber_id)

    def _fiber_prefer_bake(self, fiber):
        try:
            return bool(fiber.get("af_prefer_bake", False))
        except Exception:
            return False

    def _set_fiber_prefer_bake(self, fiber, value):
        try:
            fiber["af_prefer_bake"] = bool(value)
        except Exception:
            pass

    def _get_vis_collection(self, scene):
        return get_vis_collection(scene, self.collection_name)

    def _find_fiber_proxy(self, vis_col, root_name, fiber_id):
        return find_fiber_proxy(vis_col, root_name, fiber_id)

    def _find_endpoint_handle(self, vis_col, root_name, fiber_id, endpoint):
        return find_endpoint_handle(vis_col, root_name, fiber_id, endpoint)

    def _find_touch_handle(self, vis_col, root_name, fiber_id, touch_index):
        return find_touch_handle(vis_col, root_name, fiber_id, touch_index)

    def _create_endpoint_handle(self, vis_col, root, fiber_id, endpoint):
        return create_endpoint_handle(vis_col, root, fiber_id, endpoint)

    def _create_touch_handle(self, vis_col, root, fiber_id, touch_index):
        return create_touch_handle(vis_col, root, fiber_id, touch_index)

    def _set_fiber_color(self, obj, color):
        set_fiber_color(obj, color)

    def _create_fiber_proxy(self, vis_col, root, fiber_id):
        return create_fiber_proxy(vis_col, root, fiber_id, DEFAULT_FIBER_COLOR)

    def _update_curve_points(self, obj, points, thickness, bake=False, cyclic=False):
        update_curve_points(obj, points, thickness, bake=bake, cyclic=cyclic)

    def _fiber_cyclic(self, fiber):
        return is_loop_fiber(fiber)

    def _get_scp_proxy(self, scene, root_name, scp_id):
        return get_scp_proxy(scene, root_name, scp_id)

    def _endpoint_world(self, root, scene, runtime_registry, parent_id, attach_param_raw):
        return endpoint_world(root, scene, runtime_registry, parent_id, attach_param_raw)

    def _nearest_param(self, parent_scp, parent_proxy, moved_world):
        return nearest_param(parent_scp, parent_proxy, moved_world)

    def _nearest_parent_mesh_vertex_local_point(self, parent_proxy, moved_world):
        return nearest_parent_mesh_vertex_local_point(parent_proxy, moved_world)

    def _world_units_per_pixel(self, world_loc, window_manager=None):
        return world_units_per_pixel(world_loc, window_manager)

    def _set_helper_screen_size(self, obj, px=14.0, min_size=0.005, max_size=0.25, window_manager=None):
        wupp = self._world_units_per_pixel(obj.location, window_manager)
        if wupp is None:
            return
        obj.empty_display_size = max(min_size, min(max_size, px * wupp))

    def _sync_handles(self, root, scene, vis_col, runtime_registry, window_manager=None):
        return _sync_handles_runtime(self, root, scene, vis_col, runtime_registry, window_manager=window_manager)

    def _apply_selection_highlight(self, root, scene):
        return _apply_selection_highlight_runtime(self, root, scene)

    def refresh_selection(self, root=None, scene=None, window_manager=None):
        return _refresh_selection_runtime(self, root=root, scene=scene, window_manager=window_manager)

    def sync_root_to_scene(self, root=None, scene=None, bake=False, target_fiber_ids=None, window_manager=None):
        return _sync_root_to_scene_runtime(
            self, root=root, scene=scene, bake=bake, target_fiber_ids=target_fiber_ids, window_manager=window_manager
        )

    def on_depsgraph_update(self, scene, depsgraph):
        return _on_depsgraph_update_runtime(self, scene, depsgraph)

_FIBER_SYNC = None


def register_fiber_sync():
    global _FIBER_SYNC
    if _FIBER_SYNC is None:
        _FIBER_SYNC = FiberSceneSync()
    h = _FIBER_SYNC.on_depsgraph_update
    if h not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(h)
    return _FIBER_SYNC


def unregister_fiber_sync():
    global _FIBER_SYNC
    if _FIBER_SYNC is None:
        return
    h = _FIBER_SYNC.on_depsgraph_update
    if h in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(h)
    _FIBER_SYNC = None
