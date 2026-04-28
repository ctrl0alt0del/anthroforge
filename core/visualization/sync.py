import bpy

from ..utils import get_af_root
from .sync_runtime import on_depsgraph_update as _on_depsgraph_update_runtime
from .sync_runtime import sync_root_to_scene as _sync_root_to_scene_runtime


class SCPSceneSync:
    def __init__(self, collection_name="AF_VIS", mirror_collection_name="AF_SCP_MIRRORS"):
        self.collection_name = collection_name
        self._shape_sync_extensions = []
        self.mirror_collection_name = mirror_collection_name
        self._syncing = False

    def _iter_scp_objects(self, scene, root_name, include_mirror=False):
        for obj in scene.objects:
            valid = obj.get("af_root_name") == root_name and (obj.get("af_scp_geometry") or obj.get("af_scp_mirror"))
            if valid and (include_mirror or not obj.get("af_scp_mirror")):
                yield obj

    def _find_scp_object(self, scene, root_name, scp_id):
        sid = str(scp_id or "")
        return next((obj for obj in self._iter_scp_objects(scene, root_name) if str(obj.get("af_scp_id") or "") == sid), None)

    def _find_mirror_object(self, scene, root_name, source_scp_id):
        sid = str(source_scp_id or "")
        return next((obj for obj in self._iter_scp_objects(scene, root_name, include_mirror=True) if obj.get("af_scp_mirror") and str(obj.get("af_source_scp_id") or "") == sid), None)

    def _get_mirror_collection(self, scene):
        collection = scene.collection.children.get(self.mirror_collection_name)
        if collection is None:
            collection = bpy.data.collections.new(self.mirror_collection_name)
            scene.collection.children.link(collection)
        return collection

    def sync_root_to_scene(self, root=None, scene=None, target_scp_ids=None, attachment_parent_ids=None, attachment_gate_meta=None):
        return _sync_root_to_scene_runtime(self, root=root, scene=scene, target_scp_ids=target_scp_ids, attachment_parent_ids=attachment_parent_ids, attachment_gate_meta=attachment_gate_meta)

    def on_depsgraph_update(self, scene, depsgraph):
        return _on_depsgraph_update_runtime(self, scene, depsgraph)


_SYNC_MANAGER = None


def register_sync():
    global _SYNC_MANAGER
    if _SYNC_MANAGER is None:
        _SYNC_MANAGER = SCPSceneSync()
    if _SYNC_MANAGER.on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_SYNC_MANAGER.on_depsgraph_update)
    return _SYNC_MANAGER


def unregister_sync():
    global _SYNC_MANAGER
    if _SYNC_MANAGER is None:
        return
    if _SYNC_MANAGER.on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_SYNC_MANAGER.on_depsgraph_update)
    _SYNC_MANAGER = None
