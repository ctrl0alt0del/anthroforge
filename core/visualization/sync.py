import bpy

from ..attachment_codec import parse_scp_attach_descriptor
from ..deps.transform_behaviors import compose_attachment_world_matrix
from .sync_runtime import (
    sync_root_to_scene as _sync_root_to_scene_runtime,
    on_depsgraph_update as _on_depsgraph_update_runtime,
)
from .scp_sync_helpers import (
    matrix_to_flat,
    is_synced_matrix,
    is_user_translate_active,
    world_matrix_from_mesh_anchor,
    frame_basis3,
    nearest_parent_param,
    world_matrix_from_surface_frame,
    nearest_mesh_point_local,
)
from .colors import next_color
from .scp_sync import (
    CurveSCPSyncExtension,
    EllipsoidSCPSyncExtension,
    MeshAssetSCPSyncExtension,
    ParallelepipedSCPSyncExtension,
)


class SCPSceneSync:
    def __init__(self, collection_name="AF_VIS"):
        self.collection_name = collection_name
        self._syncing = False
        self._shape_sync_extensions = [
            CurveSCPSyncExtension(),
            EllipsoidSCPSyncExtension(),
            MeshAssetSCPSyncExtension(),
            ParallelepipedSCPSyncExtension(),
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

        slot = 0
        for i, p in enumerate(root.af_scp_system.scps):
            if p.id == scp.id:
                slot = i
                break
        color = next_color(slot)
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

    def _matrix_to_flat(self, m):
        return matrix_to_flat(m)

    def _mark_synced_matrix(self, obj):
        try:
            obj["af_last_synced_mw"] = self._matrix_to_flat(obj.matrix_world)
        except Exception:
            pass

    def _is_synced_matrix(self, obj, eps=1e-6):
        return is_synced_matrix(obj, eps=eps)

    def _is_user_translate_active(self):
        return is_user_translate_active()

    def _world_matrix_from_mesh_anchor(self, scp, parent_proxy, parent_local_point, child_local_point):
        return world_matrix_from_mesh_anchor(scp, parent_proxy, parent_local_point, child_local_point)

    def _safe_normalize(self, v, fallback):
        return v.normalized() if v.length > 1e-8 else fallback.copy()

    def _frame_basis3(self, tangent, normal):
        return frame_basis3(tangent, normal)

    def _nearest_parent_param(self, parent_scp, parent_proxy, target_world):
        return nearest_parent_param(parent_scp, parent_proxy, target_world)

    def _world_matrix_from_surface_frame(self, scp, parent_scp, parent_proxy, payload):
        return world_matrix_from_surface_frame(scp, parent_scp, parent_proxy, payload)

    def _compute_visual_world_matrix(self, scp, runtime_registry, root, scene):
        if scp.attachment is None:
            return scp.get_world_matrix(runtime_registry)

        scp_prop = self._get_scp_prop_by_id(root, scp.id)
        if scp_prop is None:
            return scp.get_world_matrix(runtime_registry)

        mode, payload, behavior = parse_scp_attach_descriptor(scp_prop.attach_param)
        parent_proxy = self._find_proxy_in_scene(scene, root.name, scp.attachment.parent_id)
        parent_scp = runtime_registry.get(scp.attachment.parent_id)
        if parent_proxy and parent_scp:
            parent_world = parent_proxy.matrix_world.copy()
            try:
                return compose_attachment_world_matrix(
                    child_scp=scp,
                    parent_scp=parent_scp,
                    parent_world=parent_world,
                    mode=mode,
                    payload=payload,
                    behavior=behavior,
                )
            except Exception:
                pass

        return scp.get_world_matrix(runtime_registry)

    def sync_root_to_scene(self, root=None, scene=None, target_scp_ids=None):
        return _sync_root_to_scene_runtime(self, root=root, scene=scene, target_scp_ids=target_scp_ids)

    def _nearest_mesh_point_local(self, obj, target_world, depsgraph):
        return nearest_mesh_point_local(obj, target_world, depsgraph)

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
