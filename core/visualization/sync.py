import bpy

from ..utils import get_af_root
from .sync_runtime import (
    sync_root_to_scene as _sync_root_to_scene_runtime,
    on_depsgraph_update as _on_depsgraph_update_runtime,
)


class SCPSceneSync:
    def __init__(self, collection_name="AF_VIS", mirror_collection_name="AF_SCP_MIRRORS"):
        # Kept for compatibility with legacy control behavior hooks.
        self.collection_name = collection_name
        self._shape_sync_extensions = []

        self.mirror_collection_name = mirror_collection_name
        self._syncing = False

    def _iter_scp_objects(self, scene, root_name, include_mirror=False):
        for obj in scene.objects:
            if not obj.get("af_scp"):
                continue
            if obj.get("af_root_name") != root_name:
                continue
            if not include_mirror and obj.get("af_scp_mirror"):
                continue
            yield obj

    def _find_scp_object(self, scene, root_name, scp_id):
        sid = str(scp_id or "")
        for obj in self._iter_scp_objects(scene, root_name, include_mirror=False):
            if str(obj.get("af_scp_id") or "") == sid:
                return obj
        return None

    def _find_mirror_object(self, scene, root_name, source_scp_id):
        sid = str(source_scp_id or "")
        for obj in self._iter_scp_objects(scene, root_name, include_mirror=True):
            if not obj.get("af_scp_mirror"):
                continue
            if str(obj.get("af_source_scp_id") or "") == sid:
                return obj
        return None

    def _get_mirror_collection(self, scene):
        col = scene.collection.children.get(self.mirror_collection_name)
        if col is None:
            col = bpy.data.collections.new(self.mirror_collection_name)
            scene.collection.children.link(col)
        return col

    def _matrix_to_flat(self, m):
        return [
            float(m[0][0]), float(m[0][1]), float(m[0][2]), float(m[0][3]),
            float(m[1][0]), float(m[1][1]), float(m[1][2]), float(m[1][3]),
            float(m[2][0]), float(m[2][1]), float(m[2][2]), float(m[2][3]),
            float(m[3][0]), float(m[3][1]), float(m[3][2]), float(m[3][3]),
        ]

    def _mark_synced_matrix(self, obj):
        try:
            obj["af_last_synced_mw"] = self._matrix_to_flat(obj.matrix_world)
        except Exception:
            pass

    def _is_synced_matrix(self, obj, eps=1e-6):
        raw = obj.get("af_last_synced_mw")
        if not isinstance(raw, (list, tuple)) or len(raw) != 16:
            return False
        cur = self._matrix_to_flat(obj.matrix_world)
        for a, b in zip(cur, raw):
            if abs(float(a) - float(b)) > eps:
                return False
        return True

    def _get_scp_prop_by_id(self, root, scp_id):
        sid = str(scp_id or "")
        for scp in root.af_scp_system.scps:
            if str(getattr(scp, "id", "") or "") == sid:
                return scp
        return None

    def sync_root_to_scene(self, root=None, scene=None, target_scp_ids=None):
        return _sync_root_to_scene_runtime(self, root=root, scene=scene, target_scp_ids=target_scp_ids)

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
