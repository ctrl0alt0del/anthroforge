import bpy
import bmesh
from mathutils import Vector

from ..utils import get_af_root
from ..vcp.blob import BlobVCPRuntime
from ..vcp.blob_solver import BlobSolver


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
        col = scene.collection.children.get(self.collection_name)
        if col is None:
            col = bpy.data.collections.new(self.collection_name)
            scene.collection.children.link(col)
        return col

    def _find_blob_proxy(self, vis_col, root_name, blob_id):
        for obj in vis_col.objects:
            if (
                obj.get("af_blob_proxy")
                and obj.get("af_root_name") == root_name
                and obj.get("af_blob_id") == blob_id
                and not obj.get("af_blob_mirror_proxy")
            ):
                return obj
        return None

    def _find_blob_control(self, vis_col, root_name, blob_id):
        for obj in vis_col.objects:
            if (
                obj.get("af_blob_control_gizmo")
                and obj.get("af_root_name") == root_name
                and obj.get("af_blob_id") == blob_id
            ):
                return obj
        return None

    def _create_blob_proxy(self, vis_col, root, blob_id):
        mesh = bpy.data.meshes.new(f"AF_{blob_id}_mesh")
        obj = bpy.data.objects.new(f"AF_{blob_id}", mesh)
        obj["af_blob_proxy"] = True
        obj["af_root_name"] = root.name
        obj["af_blob_id"] = blob_id
        vis_col.objects.link(obj)
        return obj

    def _create_blob_control(self, vis_col, root, blob_id):
        ctrl = bpy.data.objects.new(f"AF_{blob_id}_CTRL", None)
        ctrl.empty_display_type = "SPHERE"
        ctrl.empty_display_size = 0.04
        ctrl.show_in_front = True
        ctrl.hide_render = True
        ctrl["af_blob_control_gizmo"] = True
        ctrl["af_root_name"] = root.name
        ctrl["af_blob_id"] = blob_id
        vis_col.objects.link(ctrl)
        return ctrl

    def _ensure_blob_material(self, obj, active=False):
        if obj.data is None or not hasattr(obj.data, "materials"):
            return
        name = f"AF_BLOB_MAT_{obj.get('af_blob_id', obj.name)}"
        mat = bpy.data.materials.get(name)
        if mat is None:
            mat = bpy.data.materials.new(name)
            mat.use_nodes = False
        mat.diffuse_color = SELECTED_BLOB_COLOR if active else DEFAULT_BLOB_COLOR
        obj.data.materials.clear()
        obj.data.materials.append(mat)

    def _remove_proxy(self, obj):
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)

    def _remove_ctrl(self, obj):
        bpy.data.objects.remove(obj, do_unlink=True)

    def _target_object_for_blob(self, scene, root, blob_prop):
        t = blob_prop.attach_target_type
        if t == "MUSCLE" and blob_prop.attach_target_id:
            for o in scene.objects:
                if (
                    o.get("af_muscle_proxy")
                    and o.get("af_root_name") == root.name
                    and o.get("af_muscle_id") == blob_prop.attach_target_id
                    and o.get("af_muscle_surface") == "INFL"
                ):
                    return o
            for o in scene.objects:
                if (
                    o.get("af_muscle_proxy")
                    and o.get("af_root_name") == root.name
                    and o.get("af_muscle_id") == blob_prop.attach_target_id
                    and o.get("af_muscle_surface") == "BASE"
                ):
                    return o

        if t == "SCP" and blob_prop.attach_target_id:
            for o in scene.objects:
                if (
                    o.get("af_proxy")
                    and not o.get("af_mirror_proxy")
                    and o.get("af_root_name") == root.name
                    and o.get("af_scp_id") == blob_prop.attach_target_id
                ):
                    return o

        if t == "OBJECT" and blob_prop.attach_target_object_name:
            return scene.objects.get(blob_prop.attach_target_object_name)

        return None

    def _unit_local_mesh(self, blob):
        subd = 1
        if blob.resolution >= 24:
            subd = 2
        if blob.resolution >= 64:
            subd = 3
        if blob.resolution >= 128:
            subd = 4

        bm = bmesh.new()
        try:
            bmesh.ops.create_icosphere(bm, subdivisions=subd, radius=1.0)
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            verts_local = [v.co.copy() for v in bm.verts]
            faces = [tuple(v.index for v in f.verts) for f in bm.faces]
            return verts_local, faces
        finally:
            bm.free()

    def _apply_initial_transform_from_prop(self, obj, bp):
        obj.location = Vector(bp.center_world)
        if bp.shape == "ELLIPSOID":
            obj.scale = Vector((
                max(1e-6, bp.radius * bp.axis_scale[0]),
                max(1e-6, bp.radius * bp.axis_scale[1]),
                max(1e-6, bp.radius * bp.axis_scale[2]),
            ))
        else:
            r = max(1e-6, bp.radius)
            obj.scale = Vector((r, r, r))

    def _runtime_from_proxy_transform(self, bp, obj):
        runtime = BlobVCPRuntime.from_prop(bp)
        runtime.center_world = obj.matrix_world.to_translation().copy()
        return runtime

    def _update_mesh_from_world(self, obj, world_verts, faces):
        mesh = obj.data
        mesh.clear_geometry()

        m_inv = obj.matrix_world.inverted()
        local_verts = [m_inv @ v for v in world_verts]
        verts = [(v.x, v.y, v.z) for v in local_verts]

        mesh.from_pydata(verts, [], faces)
        mesh.update()

    def _vec_changed(self, a, b, eps=1e-8):
        return (Vector(a) - Vector(b)).length > eps

    def sync_root_to_scene(self, root=None, scene=None, target_blob_ids=None):
        if self._syncing:
            return

        scene = scene or bpy.context.scene
        root = root or get_af_root(scene)
        if root is None or not hasattr(root, "af_vcp_system"):
            return

        self._syncing = True
        try:
            vis_col = self._get_vis_collection(scene)
            vcp = root.af_vcp_system

            all_blob_ids = {b.id for b in vcp.blobs}
            blob_ids_to_sync = all_blob_ids if target_blob_ids is None else (set(target_blob_ids) & all_blob_ids)

            for bp in vcp.blobs:
                if bp.id not in blob_ids_to_sync:
                    continue

                obj = self._find_blob_proxy(vis_col, root.name, bp.id)
                created = False
                if obj is None:
                    obj = self._create_blob_proxy(vis_col, root, bp.id)
                    created = True

                if created:
                    self._apply_initial_transform_from_prop(obj, bp)

                ctrl = self._find_blob_control(vis_col, root.name, bp.id)
                if ctrl is None:
                    ctrl = self._create_blob_control(vis_col, root, bp.id)

                ctrl_loc = Vector((bp.control_point_world[0], bp.control_point_world[1], bp.control_point_world[2]))
                if ctrl_loc.length_squared == 0.0:
                    ctrl_loc = obj.matrix_world.to_translation().copy()
                ctrl.location = ctrl_loc

                runtime = self._runtime_from_proxy_transform(bp, obj)
                runtime.control_point_world = ctrl.location.copy()

                target_obj = self._target_object_for_blob(scene, root, bp)

                unit_local, faces = self._unit_local_mesh(runtime)
                rest_world = [obj.matrix_world @ v for v in unit_local]

                result = self._solver.solve(
                    blob=runtime,
                    target_obj=target_obj,
                    rest_world_verts=rest_world,
                    face_indices=faces,
                )

                self._update_mesh_from_world(obj, result.points, faces)

                obj["af_blob_proxy"] = True
                obj["af_root_name"] = root.name
                obj["af_blob_id"] = bp.id

                bp.last_solve_converged = bool(result.converged)
                bp.last_solve_max_disp = float(result.max_disp)
                bp.last_solve_iterations = int(result.iterations_used)

                active = (vcp.active_vcp_type == "BLOB" and vcp.active_vcp_id == bp.id)
                self._ensure_blob_material(obj, active=active)

            if target_blob_ids is None:
                for o in list(vis_col.objects):
                    if o.get("af_root_name") != root.name:
                        continue
                    if o.get("af_blob_proxy") and o.get("af_blob_id") not in all_blob_ids:
                        self._remove_proxy(o)
                    if o.get("af_blob_control_gizmo") and o.get("af_blob_id") not in all_blob_ids:
                        self._remove_ctrl(o)

        finally:
            self._syncing = False

    def on_depsgraph_update(self, scene, depsgraph):
        if self._syncing:
            return

        root = get_af_root(scene)
        if root is None or not hasattr(root, "af_vcp_system"):
            return

        changed_blob_ids = set()
        blobs_by_id = {b.id: b for b in root.af_vcp_system.blobs}

        self._syncing = True
        try:
            for upd in depsgraph.updates:
                obj = upd.id
                if not isinstance(obj, bpy.types.Object):
                    continue

                # Target object changed
                for b in root.af_vcp_system.blobs:
                    if b.attach_target_type == "OBJECT" and b.attach_target_object_name == obj.name:
                        changed_blob_ids.add(b.id)

                # Blob proxy transformed
                if (
                    obj.get("af_blob_proxy")
                    and obj.get("af_root_name") == root.name
                    and obj.get("af_blob_id")
                ):
                    changed_blob_ids.add(obj.get("af_blob_id"))

                # Blob control gizmo moved
                if (
                    obj.get("af_blob_control_gizmo")
                    and obj.get("af_root_name") == root.name
                    and obj.get("af_blob_id")
                ):
                    bid = obj.get("af_blob_id")
                    b = blobs_by_id.get(bid)
                    if b is not None:
                        new_loc = obj.location.copy()
                        if self._vec_changed(b.control_point_world, new_loc):
                            b.control_point_world = (new_loc.x, new_loc.y, new_loc.z)
                            changed_blob_ids.add(bid)

        finally:
            self._syncing = False

        if changed_blob_ids:
            from .sync_runner import sync_from_blob_ids
            sync_from_blob_ids(root=root, scene=scene, blob_ids=changed_blob_ids)


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
