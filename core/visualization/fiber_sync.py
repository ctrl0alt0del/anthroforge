import json
import bpy
from mathutils import Vector
from ..utils import get_af_root
from ..registry import SCPRegistry

class FiberSceneSync:
    def __init__(self, collection_name="AF_VCP_VIS"):
        self.collection_name = collection_name

    def _get_vis_collection(self, scene):
        col = scene.collection.children.get(self.collection_name)
        if col is None:
            col = bpy.data.collections.new(self.collection_name)
            scene.collection.children.link(col)
        return col

    def _find_fiber_proxy(self, vis_col, root_name, fiber_id):
        for obj in vis_col.objects:
            if obj.get("af_fiber_proxy") and obj.get("af_root_name") == root_name and obj.get("af_fiber_id") == fiber_id:
                return obj
        return None

    def _create_fiber_proxy(self, vis_col, root, fiber_id):
        curve = bpy.data.curves.new(f"AF_{fiber_id}_curve", type="CURVE")
        curve.dimensions = "3D"
        curve.resolution_u = 12

        obj = bpy.data.objects.new(f"AF_{fiber_id}", curve)
        obj["af_fiber_proxy"] = True
        obj["af_root_name"] = root.name
        obj["af_fiber_id"] = fiber_id

        obj.parent = root
        obj.matrix_parent_inverse = root.matrix_world.inverted()

        vis_col.objects.link(obj)
        return obj

    def _get_scp_proxy(self, scene, root_name, scp_id):
        for obj in scene.objects:
            if obj.get("af_proxy") and obj.get("af_root_name") == root_name and obj.get("af_scp_id") == scp_id:
                return obj
        return None

    def _attach_world_pos(self, root, scene, scp_id, attach_param_raw):
    # Find runtime SCP (has shape instance)
      runtime = SCPRegistry(root)
      runtime.build()
      scp = runtime.registry.get(scp_id)
      if scp is None:
          return None

      # Parse stored attach param
      try:
          param = json.loads(attach_param_raw) if attach_param_raw else 0.0
      except Exception:
          param = 0.0

      # Find proxy transform (world matrix)
      scp_proxy = self._get_scp_proxy(scene, root.name, scp_id)
      if scp_proxy is None:
          return None

      # Local attach point on shape -> world
      local_pt = scp.shape.compute_local_point(param)
      return scp_proxy.matrix_world @ local_pt

    def _update_curve(self, obj, p0, p1, thickness):
        curve = obj.data
        while curve.splines:
            curve.splines.remove(curve.splines[0])

        spline = curve.splines.new(type="POLY")
        spline.points.add(1)
        spline.points[0].co = (p0.x, p0.y, p0.z, 1.0)
        spline.points[1].co = (p1.x, p1.y, p1.z, 1.0)

        curve.bevel_depth = max(0.0, float(thickness))
        curve.fill_mode = "FULL"

    def sync_root_to_scene(self, root=None, scene=None):
        scene = scene or bpy.context.scene
        root = root or get_af_root(scene)
        if root is None:
            return
        if not hasattr(root, "af_vcp_system"):
            return

        vis_col = self._get_vis_collection(scene)

        live_ids = set()
        for fiber in root.af_vcp_system.fibers:
            live_ids.add(fiber.id)

            obj = self._find_fiber_proxy(vis_col, root.name, fiber.id)
            if obj is None:
                obj = self._create_fiber_proxy(vis_col, root, fiber.id)

            a_proxy = self._get_scp_proxy(scene, root.name, fiber.a_parent_id)
            b_proxy = self._get_scp_proxy(scene, root.name, fiber.b_parent_id)
            if a_proxy is None or b_proxy is None:
                continue

            p0 = self._attach_world_pos(root, scene, fiber.a_parent_id, fiber.a_attach_param)
            p1 = self._attach_world_pos(root, scene, fiber.b_parent_id, fiber.b_attach_param)
            if p0 is None or p1 is None:
                continue
            self._update_curve(obj, p0, p1, fiber.thickness)

        # cleanup stale
        for obj in list(vis_col.objects):
            if obj.get("af_fiber_proxy") and obj.get("af_root_name") == root.name:
                if obj.get("af_fiber_id") not in live_ids:
                    bpy.data.objects.remove(obj, do_unlink=True)


_FIBER_SYNC = None


def register_fiber_sync():
    global _FIBER_SYNC
    if _FIBER_SYNC is None:
        _FIBER_SYNC = FiberSceneSync()
    return _FIBER_SYNC


def unregister_fiber_sync():
    global _FIBER_SYNC
    _FIBER_SYNC = None
