import bpy

from ..vcp.blob_solver import BlobSolver
from .blob_sync_helpers import (
    get_vis_collection,
    find_blob_proxy,
    find_blob_control,
    create_blob_proxy,
    create_blob_control,
    ensure_blob_material,
    remove_proxy,
    remove_ctrl,
    target_object_for_blob,
    unit_local_mesh,
    apply_initial_transform_from_prop,
    runtime_from_proxy_transform,
    update_mesh_from_world,
    vec_changed,
)
from .blob_sync_runtime import (
    sync_root_to_scene as _sync_root_to_scene_runtime,
    on_depsgraph_update as _on_depsgraph_update_runtime,
)


DEFAULT_BLOB_COLOR = (0.72, 0.52, 0.40, 0.55)
SELECTED_BLOB_COLOR = (1.00, 0.25, 0.25, 0.80)


class BlobSceneSync:
    def __init__(self, collection_name="AF_VCP_VIS"):
        self.collection_name = collection_name
        self._syncing = False
        self._solver = BlobSolver()

    def clear_solver_cache(self, blob_id=None):
        self._solver.clear_cache(blob_id)

    def _get_vis_collection(self, scene):
        return get_vis_collection(scene, self.collection_name)

    def _find_blob_proxy(self, vis_col, root_name, blob_id):
        return find_blob_proxy(vis_col, root_name, blob_id)

    def _find_blob_control(self, vis_col, root_name, blob_id):
        return find_blob_control(vis_col, root_name, blob_id)

    def _create_blob_proxy(self, vis_col, root, blob_id):
        return create_blob_proxy(vis_col, root, blob_id)

    def _create_blob_control(self, vis_col, root, blob_id):
        return create_blob_control(vis_col, root, blob_id)

    def _ensure_blob_material(self, obj, active=False):
        return ensure_blob_material(
            obj,
            active=active,
            default_blob_color=DEFAULT_BLOB_COLOR,
            selected_blob_color=SELECTED_BLOB_COLOR,
        )

    def _remove_proxy(self, obj):
        return remove_proxy(obj)

    def _remove_ctrl(self, obj):
        return remove_ctrl(obj)

    def _target_object_for_blob(self, scene, root, blob_prop):
        return target_object_for_blob(scene, root, blob_prop)

    def _unit_local_mesh(self, blob):
        return unit_local_mesh(blob)

    def _apply_initial_transform_from_prop(self, obj, bp):
        return apply_initial_transform_from_prop(obj, bp)

    def _runtime_from_proxy_transform(self, bp, obj):
        return runtime_from_proxy_transform(bp, obj)

    def _update_mesh_from_world(self, obj, world_verts, faces):
        return update_mesh_from_world(obj, world_verts, faces)

    def _vec_changed(self, a, b, eps=1e-8):
        return vec_changed(a, b, eps=eps)

    def sync_root_to_scene(self, root=None, scene=None, target_blob_ids=None):
        return _sync_root_to_scene_runtime(self, root=root, scene=scene, target_blob_ids=target_blob_ids)

    def on_depsgraph_update(self, scene, depsgraph):
        return _on_depsgraph_update_runtime(self, scene, depsgraph)


_BLOB_SYNC = None


def register_blob_sync():
    global _BLOB_SYNC
    if _BLOB_SYNC is None:
        _BLOB_SYNC = BlobSceneSync()

    h = _BLOB_SYNC.on_depsgraph_update
    if h not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(h)

    return _BLOB_SYNC


def unregister_blob_sync():
    global _BLOB_SYNC
    if _BLOB_SYNC is None:
        return

    h = _BLOB_SYNC.on_depsgraph_update
    if h in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(h)

    _BLOB_SYNC = None
