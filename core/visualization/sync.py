import json
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from ..registry import SCPRegistry
from ..utils import get_af_root
from .colors import next_color
from .scp_sync import (
    CurveSCPSyncExtension,
    EllipsoidSCPSyncExtension,
    MeshAssetSCPSyncExtension,
)


class SCPSceneSync:
    def __init__(self, collection_name="AF_VIS"):
        self.collection_name = collection_name
        self._syncing = False
        self._shape_sync_extensions = [
            CurveSCPSyncExtension(),
            EllipsoidSCPSyncExtension(),
            MeshAssetSCPSyncExtension(),
        ]

    def _get_vis_collection(self, scene):
        col = scene.collection.children.get(self.collection_name)
        if col is None:
            col = bpy.data.collections.new(self.collection_name)
            scene.collection.children.link(col)
        return col

    def _iter_root_proxies(self, vis_col, root_name):
        for obj in vis_col.objects:
            if (
                obj.get("af_proxy")
                and not obj.get("af_mirror_proxy")
                and obj.get("af_root_name") == root_name
            ):
                yield obj

    def _find_proxy(self, vis_col, root_name, scp_id):
        for obj in self._iter_root_proxies(vis_col, root_name):
            if obj.get("af_scp_id") == scp_id:
                return obj
        return None

    def _find_proxy_in_scene(self, scene, root_name, scp_id):
        for obj in scene.objects:
            if (
                obj.get("af_proxy")
                and not obj.get("af_mirror_proxy")
                and obj.get("af_root_name") == root_name
                and obj.get("af_scp_id") == scp_id
            ):
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
        for scp_prop in root.af_scp_system.scps:
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

    def _create_proxy(self, vis_col, root, scp):
        data = self._new_data_block(scp)
        obj = bpy.data.objects.new(f"AF_{scp.id}", data)
        obj["af_proxy"] = True
        obj["af_root_name"] = root.name
        obj["af_scp_id"] = scp.id

        obj.parent = root
        obj.matrix_parent_inverse = root.matrix_world.inverted()

        color = next_color()
        mat_name = f"AF_SCP_MAT_{scp.id}"
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = False
        mat.diffuse_color = color
        if hasattr(obj.data, "materials"):
            obj.data.materials.clear()
            obj.data.materials.append(mat)

        vis_col.objects.link(obj)
        return obj

    def _replace_proxy_data(self, obj, scp):
        old_data = obj.data
        obj.data = self._new_data_block(scp)
        if old_data and old_data.users == 0:
            if isinstance(old_data, bpy.types.Mesh):
                bpy.data.meshes.remove(old_data)
            elif isinstance(old_data, bpy.types.Curve):
                bpy.data.curves.remove(old_data)

    def _decode_attach_param(self, raw):
        raw = (raw or "").strip()
        if not raw:
            return ("legacy", 0.0)

        try:
            data = json.loads(raw)
        except Exception:
            return ("legacy", 0.0)

        if isinstance(data, dict) and data.get("mode") == "mesh_anchor":
            p = data.get("parent_local_point")
            if isinstance(p, (list, tuple)) and len(p) == 3:
                return ("mesh_anchor", Vector((float(p[0]), float(p[1]), float(p[2]))))

        return ("legacy", data)

    def _encode_mesh_anchor(self, parent_local_point):
        return json.dumps(
            {
                "mode": "mesh_anchor",
                "parent_local_point": [
                    float(parent_local_point.x),
                    float(parent_local_point.y),
                    float(parent_local_point.z),
                ],
            }
        )

    def _world_matrix_from_mesh_anchor(self, scp, parent_proxy, parent_local_point):
        anchor_world = parent_proxy.matrix_world @ parent_local_point
        T = Matrix.Translation(anchor_world)
        R = scp.local_rotation.to_4x4()
        S = Matrix.Diagonal((*scp.local_scale, 1.0))
        return T @ R @ S

    def _compute_visual_world_matrix(self, scp, runtime_registry, root, scene):
        if scp.attachment is None:
            return scp.get_world_matrix(runtime_registry)

        scp_prop = self._get_scp_prop_by_id(root, scp.id)
        if scp_prop is None:
            return scp.get_world_matrix(runtime_registry)

        mode, payload = self._decode_attach_param(scp_prop.attach_param)
        if mode == "mesh_anchor":
            parent_proxy = self._find_proxy_in_scene(scene, root.name, scp.attachment.parent_id)
            if parent_proxy:
                return self._world_matrix_from_mesh_anchor(scp, parent_proxy, payload)

        return scp.get_world_matrix(runtime_registry)

    def sync_root_to_scene(self, root=None, scene=None, target_scp_ids=None):
        if self._syncing:
            return

        scene = scene or bpy.context.scene
        root = root or get_af_root(scene)
        if root is None or scene is None:
            return

        self._syncing = True
        try:
            vis_col = self._get_vis_collection(scene)

            runtime = SCPRegistry(root)
            runtime.build()

            all_live_ids = set(runtime.registry.keys())
            if target_scp_ids is None:
                ids_to_sync = all_live_ids
            else:
                ids_to_sync = set(target_scp_ids) & all_live_ids

            for scp_id in ids_to_sync:
                scp = runtime.registry.get(scp_id)
                if scp is None:
                    continue

                obj = self._find_proxy(vis_col, root.name, scp_id)
                if obj is None:
                    obj = self._create_proxy(vis_col, root, scp)
                elif not self._object_matches_shape(obj, scp):
                    self._replace_proxy_data(obj, scp)

                obj["af_proxy"] = True
                obj["af_root_name"] = root.name
                obj["af_scp_id"] = scp.id
                if obj.parent != root:
                    obj.parent = root
                    obj.matrix_parent_inverse = root.matrix_world.inverted()

                scp.shape.ensure_proxy_object(obj)
                obj.matrix_world = self._compute_visual_world_matrix(scp, runtime.registry, root, scene)

            for ext in self._shape_sync_extensions:
                ext.sync_post(self, root, scene, vis_col)

            if target_scp_ids is None:
                for obj in list(self._iter_root_proxies(vis_col, root.name)):
                    if obj.get("af_scp_id") not in all_live_ids:
                        self._remove_proxy(obj)
        finally:
            self._syncing = False

    def _nearest_parent_mesh_point_local(self, parent_proxy, child_world_loc, depsgraph):
        try:
            bvh = BVHTree.FromObject(parent_proxy, depsgraph)
        except Exception:
            return None

        if bvh is None:
            return None

        child_local = parent_proxy.matrix_world.inverted() @ child_world_loc
        nearest = bvh.find_nearest(child_local)
        if nearest is None:
            return None

        co, _normal, _index, _dist = nearest
        if co is None:
            return None

        return co.copy()

    def _write_proxy_transform_to_data(self, root, proxy_obj, scene, depsgraph):
        scp_id = proxy_obj.get("af_scp_id")
        if not scp_id:
            return False, None

        scp_prop = self._get_scp_prop_by_id(root, scp_id)
        if scp_prop is None:
            return False, None

        runtime = SCPRegistry(root)
        runtime.build()

        if scp_prop.parent_id:
            parent = runtime.registry.get(scp_prop.parent_id)
            child = runtime.registry.get(scp_id)
            if parent is None or child is None:
                return False, None

            parent_proxy = self._find_proxy_in_scene(scene, root.name, scp_prop.parent_id)
            if parent_proxy is None:
                return False, None

            child_world_loc = proxy_obj.matrix_world.to_translation()
            parent_local_point = self._nearest_parent_mesh_point_local(parent_proxy, child_world_loc, depsgraph)
            if parent_local_point is None:
                return False, None

            scp_prop.attach_param = self._encode_mesh_anchor(parent_local_point)

            anchor_world = parent_proxy.matrix_world @ parent_local_point
            local_matrix = Matrix.Translation(anchor_world).inverted() @ proxy_obj.matrix_world
            _loc, rot, scale = local_matrix.decompose()

            scp_prop.local_origin = (0.0, 0.0, 0.0)
            scp_prop.local_rotation = (rot.w, rot.x, rot.y, rot.z)
            scp_prop.local_scale = (scale.x, scale.y, scale.z)
            return True, scp_id

        local_matrix = proxy_obj.matrix_world
        loc, rot, scale = local_matrix.decompose()

        scp_prop.local_origin = (loc.x, loc.y, loc.z)
        scp_prop.local_rotation = (rot.w, rot.x, rot.y, rot.z)
        scp_prop.local_scale = (scale.x, scale.y, scale.z)
        return True, scp_id

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
        changed_scp_ids = set()

        self._syncing = True
        try:
            for update in depsgraph.updates:
                obj = update.id
                if not isinstance(obj, bpy.types.Object):
                    continue
                if obj.get("af_root_name") != root.name:
                    continue
                if vis_col.objects.get(obj.name) is None:
                    continue

                consumed = False
                for ext in self._shape_sync_extensions:
                    ext_consumed, did, sid = ext.handle_object_update(self, root, scene, vis_col, obj, depsgraph)
                    if not ext_consumed:
                        continue
                    consumed = True
                    changed |= did
                    if sid:
                        changed_scp_ids.add(sid)
                    break
                if consumed:
                    continue

                if not obj.get("af_proxy"):
                    continue
                if obj.get("af_mirror_proxy"):
                    continue

                did, sid = self._write_proxy_transform_to_data(root, obj, scene, depsgraph)
                changed |= did
                if sid:
                    changed_scp_ids.add(sid)
        finally:
            self._syncing = False

        if changed and changed_scp_ids:
            from .sync_runner import sync_from_scp_ids
            sync_from_scp_ids(root=root, scene=scene, scp_ids=changed_scp_ids)


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
