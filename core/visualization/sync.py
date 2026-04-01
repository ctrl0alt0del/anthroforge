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
    ParallelepipedSCPSyncExtension,
)


class SCPSceneSync:
    def __init__(self, collection_name="AF_VIS"):
        self.collection_name = collection_name
        self._syncing = False
        self._last_active_scp_id = ""
        self._shape_sync_extensions = [
            CurveSCPSyncExtension(),
            EllipsoidSCPSyncExtension(),
            MeshAssetSCPSyncExtension(),
            ParallelepipedSCPSyncExtension(),
        ]

    def _active_scp_id_from_context(self, root):
        if bpy.context is None or bpy.context.view_layer is None:
            return ""
        active_obj = bpy.context.view_layer.objects.active
        if active_obj is None:
            return ""
        if active_obj.get("af_root_name") != root.name:
            return ""

        if active_obj.get("af_scp_id"):
            if (
                active_obj.get("af_proxy")
                or active_obj.get("af_curve_point_handle")
                or active_obj.get("af_parallelepiped_vert_handle")
                or active_obj.get("af_ellipsoid_clip_handle")
            ):
                return str(active_obj.get("af_scp_id"))
        return ""

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

    def _is_user_translate_active(self):
        """
        True only while a viewport translate operation is currently active.
        We use this as inverse-authoring intent for attached SCP reprojection.
        """
        try:
            wm = bpy.context.window_manager
            ops = getattr(wm, "operators", None) or []
            for op in reversed(list(ops)):
                bid = getattr(op, "bl_idname", "") or ""
                if bid == "TRANSFORM_OT_translate":
                    return True
                if bid == "TRANSFORM_OT_transform":
                    mode = str(getattr(getattr(op, "properties", None), "mode", "") or "")
                    if mode == "TRANSLATION":
                        return True
            return False
        except Exception:
            return False

    def _decode_attach_param(self, raw):
        raw = (raw or "").strip()
        if not raw:
            return ("legacy", 0.0)

        try:
            data = json.loads(raw)
        except Exception:
            return ("legacy", 0.0)

        def _vec3(value, fallback):
            if isinstance(value, (list, tuple)) and len(value) == 3:
                return Vector((float(value[0]), float(value[1]), float(value[2])))
            return fallback.copy()

        if isinstance(data, dict) and data.get("mode") == "surface_frame_v1":
            return (
                "surface_frame_v1",
                {
                    "parent_param": data.get("parent_param", 0.0),
                    "child_origin_local": _vec3(
                        data.get("child_origin_local", data.get("child_local_point")),
                        Vector((0.0, 0.0, 0.0)),
                    ),
                    "child_tangent_local": _vec3(
                        data.get("child_tangent_local"),
                        Vector((1.0, 0.0, 0.0)),
                    ),
                    "child_normal_local": _vec3(
                        data.get("child_normal_local"),
                        Vector((0.0, 0.0, 1.0)),
                    ),
                },
            )

        if isinstance(data, dict) and data.get("mode") == "mesh_anchor":
            p = data.get("parent_local_point")
            c = data.get("child_local_point")
            if (
                isinstance(p, (list, tuple)) and len(p) == 3
                and isinstance(c, (list, tuple)) and len(c) == 3
            ):
                return (
                    "mesh_anchor",
                    (
                        Vector((float(p[0]), float(p[1]), float(p[2]))),
                        Vector((float(c[0]), float(c[1]), float(c[2]))),
                    ),
                )
            if isinstance(p, (list, tuple)) and len(p) == 3:
                return (
                    "mesh_anchor",
                    (
                        Vector((float(p[0]), float(p[1]), float(p[2]))),
                        Vector((0.0, 0.0, 0.0)),
                    ),
                )

        return ("legacy", data)

    def _json_safe_param(self, value):
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                out[str(k)] = self._json_safe_param(v)
            return out
        if isinstance(value, Vector):
            return [float(value.x), float(value.y), float(value.z)]
        if isinstance(value, (list, tuple)):
            return [self._json_safe_param(v) for v in value]
        if isinstance(value, (int, float, str, bool)) or value is None:
            return value
        try:
            return float(value)
        except Exception:
            return 0.0

    def _encode_surface_frame(
        self, parent_param, child_origin_local, child_tangent_local, child_normal_local, parent_local_point=None
    ):
        payload = {
            "mode": "surface_frame_v1",
            "parent_param": self._json_safe_param(parent_param),
            "child_origin_local": [
                float(child_origin_local.x),
                float(child_origin_local.y),
                float(child_origin_local.z),
            ],
            "child_tangent_local": [
                float(child_tangent_local.x),
                float(child_tangent_local.y),
                float(child_tangent_local.z),
            ],
            "child_normal_local": [
                float(child_normal_local.x),
                float(child_normal_local.y),
                float(child_normal_local.z),
            ],
        }
        if parent_local_point is not None:
            payload["parent_local_point"] = [
                float(parent_local_point.x),
                float(parent_local_point.y),
                float(parent_local_point.z),
            ]
        return json.dumps(payload)

    def _encode_mesh_anchor(self, parent_local_point, child_local_point):
        return json.dumps(
            {
                "mode": "mesh_anchor",
                "parent_local_point": [
                    float(parent_local_point.x),
                    float(parent_local_point.y),
                    float(parent_local_point.z),
                ],
                "child_local_point": [
                    float(child_local_point.x),
                    float(child_local_point.y),
                    float(child_local_point.z),
                ],
            }
        )

    def _world_matrix_from_mesh_anchor(self, scp, parent_proxy, parent_local_point, child_local_point):
        anchor_world = parent_proxy.matrix_world @ parent_local_point
        RS = scp.local_rotation.to_4x4() @ Matrix.Diagonal((*scp.local_scale, 1.0))
        child_off = RS @ Vector((child_local_point.x, child_local_point.y, child_local_point.z, 1.0))
        obj_origin = anchor_world - Vector((child_off.x, child_off.y, child_off.z))
        return Matrix.Translation(obj_origin) @ RS

    def _safe_normalize(self, v, fallback):
        out = v.copy()
        if out.length <= 1e-8:
            return fallback.copy()
        out.normalize()
        return out

    def _frame_basis3(self, tangent, normal):
        t = self._safe_normalize(tangent, Vector((1.0, 0.0, 0.0)))
        n = normal - t * t.dot(normal)
        n = self._safe_normalize(n, Vector((0.0, 0.0, 1.0)))
        if abs(t.dot(n)) > 0.999:
            n = self._safe_normalize(t.cross(Vector((0.0, 1.0, 0.0))), Vector((0.0, 0.0, 1.0)))
        b = self._safe_normalize(n.cross(t), Vector((0.0, 1.0, 0.0)))
        n = self._safe_normalize(t.cross(b), Vector((0.0, 0.0, 1.0)))
        return Matrix((t, b, n)).transposed()

    def _nearest_parent_param(self, parent_scp, parent_proxy, target_world):
        params = parent_scp.shape.get_attach_params() or [0.0]
        best_param = params[0]
        best_d2 = None
        for p in params:
            lp = parent_scp.shape.compute_local_point(p)
            wp = parent_proxy.matrix_world @ lp
            d2 = (wp - target_world).length_squared
            if best_d2 is None or d2 < best_d2:
                best_d2 = d2
                best_param = p
        return best_param

    def _world_matrix_from_surface_frame(self, scp, parent_scp, parent_proxy, payload):
        parent_param = payload.get("parent_param", 0.0)
        child_origin_local = payload.get("child_origin_local", Vector((0.0, 0.0, 0.0)))
        child_tangent_local = payload.get("child_tangent_local", Vector((1.0, 0.0, 0.0)))
        child_normal_local = payload.get("child_normal_local", Vector((0.0, 0.0, 1.0)))

        p_origin_local, p_tangent_local, p_normal_local = parent_scp.shape.sample_attachment_frame_local(parent_param)
        mw = parent_proxy.matrix_world
        mw3 = mw.to_3x3()
        p_origin_world = mw @ p_origin_local
        p_tangent_world = mw3 @ p_tangent_local
        p_normal_world = mw3 @ p_normal_local

        parent_basis = self._frame_basis3(p_tangent_world, p_normal_world)
        child_basis_local = self._frame_basis3(child_tangent_local, child_normal_local)
        attach_rot = parent_basis @ child_basis_local.inverted()
        final_rot = attach_rot @ scp.local_rotation

        sx, sy, sz = float(scp.local_scale.x), float(scp.local_scale.y), float(scp.local_scale.z)
        child_off_world = final_rot @ (Matrix.Diagonal((sx, sy, sz)) @ child_origin_local)
        obj_origin = p_origin_world - child_off_world

        out = final_rot.to_4x4()
        out.translation = obj_origin
        return out

    def _compute_visual_world_matrix(self, scp, runtime_registry, root, scene):
        if scp.attachment is None:
            return scp.get_world_matrix(runtime_registry)

        scp_prop = self._get_scp_prop_by_id(root, scp.id)
        if scp_prop is None:
            return scp.get_world_matrix(runtime_registry)

        mode, payload = self._decode_attach_param(scp_prop.attach_param)
        if mode == "surface_frame_v1":
            parent_proxy = self._find_proxy_in_scene(scene, root.name, scp.attachment.parent_id)
            parent_scp = runtime_registry.get(scp.attachment.parent_id)
            if parent_proxy and parent_scp:
                return self._world_matrix_from_surface_frame(
                    scp, parent_scp, parent_proxy, payload
                )
        if mode == "mesh_anchor":
            parent_proxy = self._find_proxy_in_scene(scene, root.name, scp.attachment.parent_id)
            if parent_proxy:
                parent_local_point, child_local_point = payload
                return self._world_matrix_from_mesh_anchor(
                    scp, parent_proxy, parent_local_point, child_local_point
                )

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
                self._mark_synced_matrix(obj)

            for ext in self._shape_sync_extensions:
                ext.sync_post(self, root, scene, vis_col)

            if target_scp_ids is None:
                for obj in list(self._iter_root_proxies(vis_col, root.name)):
                    if obj.get("af_scp_id") not in all_live_ids:
                        self._remove_proxy(obj)
        finally:
            self._syncing = False

    def _nearest_mesh_point_local(self, obj, target_world, depsgraph):
        try:
            bvh = BVHTree.FromObject(obj, depsgraph)
        except Exception:
            return None

        if bvh is None:
            return None

        target_local = obj.matrix_world.inverted() @ target_world
        nearest = bvh.find_nearest(target_local)
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
            # Inverse attachment solve is editor-authoring only:
            # recompute attach/local-to-parent only during direct user translate.
            if not self._is_user_translate_active():
                return False, None

            parent = runtime.registry.get(scp_prop.parent_id)
            child = runtime.registry.get(scp_id)
            if parent is None or child is None:
                return False, None

            parent_proxy = self._find_proxy_in_scene(scene, root.name, scp_prop.parent_id)
            if parent_proxy is None:
                return False, None

            child_world_loc = proxy_obj.matrix_world.to_translation()
            parent_param = self._nearest_parent_param(parent, parent_proxy, child_world_loc)
            parent_local_point, _pt, _pn = parent.shape.sample_attachment_frame_local(parent_param)
            anchor_world = parent_proxy.matrix_world @ parent_local_point

            child_origin_local = self._nearest_mesh_point_local(proxy_obj, anchor_world, depsgraph)
            if child_origin_local is None:
                child_origin_local = Vector((0.0, 0.0, 0.0))

            mode, payload = self._decode_attach_param(scp_prop.attach_param)
            if mode == "surface_frame_v1":
                child_tangent_local = payload.get("child_tangent_local", Vector((1.0, 0.0, 0.0)))
                child_normal_local = payload.get("child_normal_local", Vector((0.0, 0.0, 1.0)))
            else:
                child_tangent_local = Vector((1.0, 0.0, 0.0))
                child_normal_local = Vector((0.0, 0.0, 1.0))

            scp_prop.attach_param = self._encode_surface_frame(
                parent_param=parent_param,
                child_origin_local=child_origin_local,
                child_tangent_local=child_tangent_local,
                child_normal_local=child_normal_local,
                parent_local_point=parent_local_point,
            )
            scp_prop.local_origin = (0.0, 0.0, 0.0)
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

        active_scp_id = self._active_scp_id_from_context(root)
        if active_scp_id != self._last_active_scp_id:
            changed_ids = set()
            if self._last_active_scp_id:
                changed_ids.add(self._last_active_scp_id)
            if active_scp_id:
                changed_ids.add(active_scp_id)
            self._last_active_scp_id = active_scp_id
            # Selection changes do not always produce transform updates, but
            # shape extensions (control points) still need a refresh.
            self.sync_root_to_scene(root=root, scene=scene, target_scp_ids=changed_ids or None)

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
                # Ignore updates that only reflect our own sync-applied matrix,
                # otherwise attached children may re-snap to another parent point.
                if self._is_synced_matrix(obj):
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
