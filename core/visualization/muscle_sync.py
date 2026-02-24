import bpy

from ..utils import get_af_root
from ..vcp.muscle_surface import (
    build_surface_data,
    validate_anchor_structure,
)


class MuscleSceneSync:
    def __init__(self, collection_name="AF_VCP_VIS"):
        self.collection_name = collection_name

    def _get_vis_collection(self, scene):
        col = scene.collection.children.get(self.collection_name)
        if col is None:
            col = bpy.data.collections.new(self.collection_name)
            scene.collection.children.link(col)
        return col

    def _find_muscle_proxy(self, vis_col, root_name, muscle_id):
        for obj in vis_col.objects:
            if (
                obj.get("af_muscle_proxy")
                and obj.get("af_root_name") == root_name
                and obj.get("af_muscle_id") == muscle_id
            ):
                return obj
        return None

    def _create_muscle_proxy(self, vis_col, root, muscle_id):
        mesh = bpy.data.meshes.new(f"AF_{muscle_id}_mesh")
        obj = bpy.data.objects.new(f"AF_{muscle_id}", mesh)
        obj["af_muscle_proxy"] = True
        obj["af_root_name"] = root.name
        obj["af_muscle_id"] = muscle_id
        vis_col.objects.link(obj)
        return obj

    def _ensure_material(self, obj, active=False):
        if obj.data is None or not hasattr(obj.data, "materials"):
            return

        mat_name = f"AF_MUSCLE_MAT_{obj.get('af_muscle_id', obj.name)}"
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            mat = bpy.data.materials.new(mat_name)
            mat.use_nodes = False

        mat.diffuse_color = (0.75, 0.25, 0.25, 0.8) if active else (0.72, 0.42, 0.32, 0.55)

        obj.data.materials.clear()
        obj.data.materials.append(mat)

    def _update_mesh(self, obj, verts, faces):
        mesh = obj.data
        mesh.clear_geometry()
        mesh.from_pydata(verts, [], faces)
        mesh.update()

    def _collect_fiber_props(self, root, muscle):
        fibers_by_id = {f.id: f for f in root.af_vcp_system.fibers}
        ordered = []
        missing = []

        for ref in muscle.fiber_refs:
            f = fibers_by_id.get(ref.fiber_id)
            if f is None:
                missing.append(ref.fiber_id)
            else:
                ordered.append(f)

        return ordered, missing

    def _collect_fiber_points(self, root, scene, fiber_props):
      # local import avoids fiber_sync <-> muscle_sync circular import at module load
      from .fiber_sync import register_fiber_sync

      fsync = register_fiber_sync()
      out = []

      for f in fiber_props:
          pts = fsync._solver.solve_points(
              root=root,
              fiber_prop=f,
              scene=scene,
              depsgraph=bpy.context.evaluated_depsgraph_get(),
              bake=True,
          )
          if len(pts) < 2:
              return None
          out.append(pts)

      return out
    def _remove_muscle_proxy(self, obj):
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)

    def sync_root_to_scene(self, root=None, scene=None):
        scene = scene or bpy.context.scene
        root = root or get_af_root(scene)
        if root is None or not hasattr(root, "af_vcp_system"):
            return

        vis_col = self._get_vis_collection(scene)
        vcp = root.af_vcp_system

        live_muscle_ids = set()

        for muscle in vcp.muscles:
            live_muscle_ids.add(muscle.id)

            obj = self._find_muscle_proxy(vis_col, root.name, muscle.id)
            if obj is None:
                obj = self._create_muscle_proxy(vis_col, root, muscle.id)

            obj["af_muscle_proxy"] = True
            obj["af_root_name"] = root.name
            obj["af_muscle_id"] = muscle.id

            ordered_fibers, missing = self._collect_fiber_props(root, muscle)
            if missing or len(ordered_fibers) < 2:
                self._update_mesh(obj, [], [])
                self._ensure_material(obj, active=(vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id))
                continue

            ok, _reason, _node_count, _anchors = validate_anchor_structure(ordered_fibers)
            if not ok:
                self._update_mesh(obj, [], [])
                self._ensure_material(obj, active=(vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id))
                continue

            ordered_points = self._collect_fiber_points(root, scene, ordered_fibers)
            if not ordered_points:
                self._update_mesh(obj, [], [])
                self._ensure_material(obj, active=(vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id))
                continue

            try:
                verts, faces, _n = build_surface_data(
                    ordered_fiber_points=ordered_points,
                    closed_v=bool(muscle.closed_v),
                )
            except Exception:
                self._update_mesh(obj, [], [])
                self._ensure_material(obj, active=(vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id))
                continue

            self._update_mesh(obj, verts, faces)
            self._ensure_material(obj, active=(vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id))

        # Cleanup stale muscle proxies
        for obj in list(vis_col.objects):
            if not obj.get("af_muscle_proxy"):
                continue
            if obj.get("af_root_name") != root.name:
                continue
            if obj.get("af_muscle_id") not in live_muscle_ids:
                self._remove_muscle_proxy(obj)


_MUSCLE_SYNC = None


def register_muscle_sync():
    global _MUSCLE_SYNC
    if _MUSCLE_SYNC is None:
        _MUSCLE_SYNC = MuscleSceneSync()
    return _MUSCLE_SYNC


def unregister_muscle_sync():
    global _MUSCLE_SYNC
    _MUSCLE_SYNC = None
