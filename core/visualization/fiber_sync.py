import bpy

from ..vcp.fiber_modes import is_loop_fiber
from ..vcp.fiber_solver import FiberSolver
from .fiber_sync_helpers import (
    clear_curve_points,
    get_vis_collection,
    find_fiber_proxy,
    find_endpoint_handle,
    find_touch_handle,
    find_loop_anchor_handle,
    create_endpoint_handle,
    create_touch_handle,
    create_loop_anchor_handle,
    set_fiber_color,
    create_fiber_proxy,
    update_curve_points,
    update_curve_style,
    get_scp_proxy,
    endpoint_world,
    nearest_param,
    world_units_per_pixel,
)
from ..vcp.attachment_backend import capture_attachment_from_object, capture_attachment_from_object_ray
from .fiber_sync_runtime import (
    sync_handles as _sync_handles_runtime,
    apply_selection_highlight as _apply_selection_highlight_runtime,
    refresh_selection as _refresh_selection_runtime,
    refresh_propagated_handles as _refresh_propagated_handles_runtime,
    sync_root_to_scene as _sync_root_to_scene_runtime,
    on_depsgraph_update as _on_depsgraph_update_runtime,
    apply_fiber_points as _apply_fiber_points_runtime,
    refresh_display as _refresh_display_runtime,
)
from . import fiber_view_capture

DEFAULT_FIBER_COLOR = (0.85, 0.55, 0.20, 1.0)
SELECTED_FIBER_COLOR = (1.0, 0.0, 0.0, 1.0)


class FiberSceneSync:
    def __init__(self, collection_name="AF_VCP_VIS", context_provider=None):
        self.collection_name = collection_name
        self._solver = FiberSolver(surface_offset=0.002)
        self._syncing = False
        self._object_index = None
        self._object_index_key = None
        self._point_batch_depth = 0
        self._context_provider = context_provider
        self.default_fiber_color = DEFAULT_FIBER_COLOR
        self.selected_fiber_color = SELECTED_FIBER_COLOR

    def begin_point_batch(self):
        self._point_batch_depth += 1

    def end_point_batch(self):
        self._point_batch_depth = max(0, self._point_batch_depth - 1)
        if not self._point_batch_depth:
            self._object_index = None; self._object_index_key = None

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
        return find_fiber_proxy(vis_col, root_name, fiber_id, self._object_index)

    def _find_endpoint_handle(self, vis_col, root_name, fiber_id, endpoint):
        return find_endpoint_handle(vis_col, root_name, fiber_id, endpoint, self._object_index)

    def _find_touch_handle(self, vis_col, root_name, fiber_id, touch_index):
        return find_touch_handle(vis_col, root_name, fiber_id, touch_index, self._object_index)

    def _find_loop_anchor_handle(self, vis_col, root_name, fiber_id, anchor_index):
        return find_loop_anchor_handle(vis_col, root_name, fiber_id, anchor_index, self._object_index)

    def _create_endpoint_handle(self, vis_col, root, fiber_id, endpoint):
        return create_endpoint_handle(vis_col, root, fiber_id, endpoint)

    def _create_touch_handle(self, vis_col, root, fiber_id, touch_index):
        return create_touch_handle(vis_col, root, fiber_id, touch_index)

    def _create_loop_anchor_handle(self, vis_col, root, fiber_id, anchor_index):
        return create_loop_anchor_handle(vis_col, root, fiber_id, anchor_index)

    def _set_fiber_color(self, obj, color):
        set_fiber_color(obj, color)

    def _create_fiber_proxy(self, vis_col, root, fiber_id):
        return create_fiber_proxy(vis_col, root, fiber_id, DEFAULT_FIBER_COLOR)

    def _update_curve_points(self, obj, points, thickness, bake=False, cyclic=False, commit=True):
        update_curve_points(obj, points, thickness, bake=bake, cyclic=cyclic, commit=commit)

    def _update_curve_style(self, obj, thickness):
        return update_curve_style(obj, thickness)

    def _clear_curve_points(self, obj):
        clear_curve_points(obj)

    def _fiber_cyclic(self, fiber):
        return is_loop_fiber(fiber)

    def _get_scp_proxy(self, scene, root_name, scp_id):
        return get_scp_proxy(scene, root_name, scp_id)

    def _endpoint_world(self, root, scene, runtime_registry, parent_id, attach_param_raw):
        return endpoint_world(root, scene, runtime_registry, parent_id, attach_param_raw)

    def _nearest_param(self, parent_scp, parent_proxy, moved_world):
        return nearest_param(parent_scp, parent_proxy, moved_world)

    def _capture_attachment_from_world(self, parent_proxy, moved_world, runtime=None):
        ray = self._view_ray_for_world_point(moved_world)
        if ray is fiber_view_capture.NO_VIEW_RAY:
            return capture_attachment_from_object(parent_proxy, moved_world, runtime)
        return None if ray is None else capture_attachment_from_object_ray(parent_proxy, *ray, runtime=runtime)

    def _view_ray_for_world_point(self, moved_world):
        context = None if self._context_provider is None else self._context_provider()
        return fiber_view_capture.view_ray_for_world_point(moved_world, context)

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

    def refresh_selection(self, root=None, scene=None, window_manager=None, fiber_ids=None, sync_handles=False):
        return _refresh_selection_runtime(self, root=root, scene=scene, window_manager=window_manager,
                                          fiber_ids=fiber_ids, sync_handles=sync_handles)

    def refresh_propagated_handles(self, root, scene, points_by_id, fiber_ids):
        return _refresh_propagated_handles_runtime(self, root, scene, points_by_id, fiber_ids)

    def refresh_display(self, root=None, scene=None, target_fiber_ids=None):
        return _refresh_display_runtime(self, root=root, scene=scene, target_fiber_ids=target_fiber_ids)

    def sync_root_to_scene(self, root=None, scene=None, bake=False, target_fiber_ids=None, window_manager=None, drain=True):
        return _sync_root_to_scene_runtime(
            self, root=root, scene=scene, bake=bake, target_fiber_ids=target_fiber_ids,
            window_manager=window_manager, drain=drain,
        )

    def apply_points(self, root, scene, fiber, points, bake=False, commit=True):
        from ..vcp.fiber_instance import MirroredFiber
        if isinstance(fiber, MirroredFiber):
            from .fiber_instance_runtime import apply_points
            return apply_points(root, scene, fiber, points, commit)
        return _apply_fiber_points_runtime(self, root, scene, fiber, points, bake=bake, commit=commit)

    def on_depsgraph_update(self, scene, depsgraph):
        return _on_depsgraph_update_runtime(self, scene, depsgraph)

_FIBER_SYNC = None


def register_fiber_sync(context_provider=None):
    global _FIBER_SYNC
    if _FIBER_SYNC is None:
        _FIBER_SYNC = FiberSceneSync(context_provider=context_provider)
    elif context_provider is not None:
        _FIBER_SYNC._context_provider = context_provider
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
