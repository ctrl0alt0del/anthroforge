# core/visualization/sync.py
import bpy
from mathutils import Matrix
from ..registry import SCPRegistry
from ..utils import get_af_root


class SCPSceneSync:
    """
    Keeps SCP data and Blender proxy objects in sync.

    Data -> Visual:
      Builds runtime SCP registry from root.af_system.scps and updates proxies.

    Visual -> Data:
      Watches proxy transform changes in depsgraph and writes transform back
      into matching SCP properties.
    """

    def __init__(self, collection_name="AF_VIS"):
        self.collection_name = collection_name
        self._syncing = False

    # ------------------------------
    # Collection / Proxy Helpers
    # ------------------------------

    def _get_vis_collection(self, scene):
        col = scene.collection.children.get(self.collection_name)
        if col is None:
            col = bpy.data.collections.new(self.collection_name)
            scene.collection.children.link(col)
        return col

    def _iter_root_proxies(self, vis_col, root_name):
        for obj in vis_col.objects:
            if obj.get("af_proxy") and obj.get("af_root_name") == root_name:
                yield obj

    def _find_proxy(self, vis_col, root_name, scp_id):
        for obj in self._iter_root_proxies(vis_col, root_name):
            if obj.get("af_scp_id") == scp_id:
                return obj
        return None

    def _remove_proxy(self, obj):
      data = obj.data if obj else None
      bpy.data.objects.remove(obj, do_unlink=True)
      if data and data.users == 0:
          if isinstance(data, bpy.types.Mesh):
              bpy.data.meshes.remove(data)
          elif isinstance(data, bpy.types.Curve):
              bpy.data.curves.remove(data)

    def _get_scp_prop_by_id(self, root, scp_id):
        for scp_prop in root.af_system.scps:
            if scp_prop.id == scp_id:
                return scp_prop
        return None

    def _new_data_block(self, scp):
      if scp.shape.proxy_data_type == "CURVE":
          return bpy.data.curves.new(f"AF_{scp.id}_curve", type="CURVE")
      return bpy.data.meshes.new(f"AF_{scp.id}_mesh")

    def _object_matches_shape(self, obj, scp):
        if scp.shape.proxy_object_type == "CURVE":
            return obj.type == "CURVE"
        return obj.type == "MESH"

    def _create_proxy(self, vis_col, root_name, scp):
        data = self._new_data_block(scp)
        obj = bpy.data.objects.new(f"AF_{scp.id}", data)
        obj["af_proxy"] = True
        obj["af_root_name"] = root_name
        obj["af_scp_id"] = scp.id
        vis_col.objects.link(obj)
        return obj

    def _replace_proxy_data(self, obj, scp):
        old_data = obj.data
        obj.data = self._new_data_block(scp)
        if old_data and old_data.users == 0:
            if old_data.__class__.__name__ == "Mesh":
                bpy.data.meshes.remove(old_data)
            elif old_data.__class__.__name__ == "Curve":
                bpy.data.curves.remove(old_data)

    # ------------------------------
    # Data -> Visual
    # ------------------------------

    def sync_root_to_scene(self, root=None, scene=None):
        if self._syncing:
            return

        root = root or get_af_root(scene)
        if root is None:
            return

        scene = scene or bpy.context.scene
        if scene is None:
            return

        self._syncing = True
        try:
            vis_col = self._get_vis_collection(scene)

            runtime = SCPRegistry(root)
            runtime.build()

            live_ids = set(runtime.registry.keys())

            # Create/update proxies
            for scp_id, scp in runtime.registry.items():
                obj = self._find_proxy(vis_col, root.name, scp_id)
                if obj is None:
                    obj = self._create_proxy(vis_col, root.name, scp)
                elif not self._object_matches_shape(obj, scp):
                    self._replace_proxy_data(obj, scp)

                scp.shape.ensure_proxy_object(obj)
                obj.matrix_world = scp.get_world_matrix(runtime.registry)

            # Remove stale proxies
            for obj in list(self._iter_root_proxies(vis_col, root.name)):
                if obj.get("af_scp_id") not in live_ids:
                    self._remove_proxy(obj)
        finally:
            self._syncing = False

    # ------------------------------
    # Visual -> Data
    # ------------------------------

    def _write_proxy_transform_to_data(self, root, proxy_obj):
        scp_id = proxy_obj.get("af_scp_id")
        if not scp_id:
            return False

        scp_prop = self._get_scp_prop_by_id(root, scp_id)
        if scp_prop is None:
            return False

        runtime = SCPRegistry(root)
        runtime.build()

        # For attached SCPs, local transform is relative to attachment anchor.
        # Existing SCP world math ignores child local_origin for attached nodes,
        # so translation is clamped to zero in data for now.
        if scp_prop.parent_id:
            parent = runtime.registry.get(scp_prop.parent_id)
            child = runtime.registry.get(scp_id)
            if parent is None or child is None or child.attachment is None:
                return False

            parent_world = parent.get_world_matrix(runtime.registry)
            attach_local = parent.shape.compute_local_point(child.attachment.param)
            attach_world = parent_world @ attach_local
            anchor_world = Matrix.Translation(attach_world)

            local_matrix = anchor_world.inverted() @ proxy_obj.matrix_world
            _loc, rot, scale = local_matrix.decompose()

            scp_prop.local_origin = (0.0, 0.0, 0.0)
            scp_prop.local_rotation = (rot.w, rot.x, rot.y, rot.z)
            scp_prop.local_scale = (scale.x, scale.y, scale.z)
            return True

        # Root-level SCP
        local_matrix = proxy_obj.matrix_world
        loc, rot, scale = local_matrix.decompose()

        scp_prop.local_origin = (loc.x, loc.y, loc.z)
        scp_prop.local_rotation = (rot.w, rot.x, rot.y, rot.z)
        scp_prop.local_scale = (scale.x, scale.y, scale.z)
        return True

    def on_depsgraph_update(self, scene, depsgraph):
        if self._syncing:
            return

        root = get_af_root(scene)
        if root is None:
            return

        vis_col = bpy.data.collections.get(self.collection_name)
        if vis_col is None:
            return

        changed = False
        self._syncing = True
        try:
            for update in depsgraph.updates:
                obj = update.id
                if not isinstance(obj, bpy.types.Object):
                    continue
                if not obj.get("af_proxy"):
                    continue
                if obj.get("af_root_name") != root.name:
                    continue
                if vis_col.objects.get(obj.name) is None:
                    continue

                changed |= self._write_proxy_transform_to_data(root, obj)
        finally:
            self._syncing = False

        # Re-apply authoritative data so proxies stay fully consistent.
        if changed:
            self.sync_root_to_scene(root=root, scene=scene)


# ------------------------------
# Module-level register helpers
# ------------------------------

_SYNC_MANAGER = None


def register_sync():
    global _SYNC_MANAGER

    if _SYNC_MANAGER is None:
        _SYNC_MANAGER = SCPSceneSync()

    if _SYNC_MANAGER.on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_SYNC_MANAGER.on_depsgraph_update)

    #_SYNC_MANAGER.sync_root_to_scene()
    return _SYNC_MANAGER


def unregister_sync():
    global _SYNC_MANAGER

    if _SYNC_MANAGER is None:
        return

    if _SYNC_MANAGER.on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_SYNC_MANAGER.on_depsgraph_update)

    _SYNC_MANAGER = None
