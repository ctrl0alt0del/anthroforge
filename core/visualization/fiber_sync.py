import bpy

from ..utils import get_af_root
from ..vcp.fiber_solver import FiberSolver

DEFAULT_FIBER_COLOR = (0.85, 0.55, 0.20, 1.0)
SELECTED_FIBER_COLOR = (1.0, 0.0, 0.0, 1.0)


class FiberSceneSync:
    def __init__(self, collection_name="AF_VCP_VIS"):
        self.collection_name = collection_name
        self._solver = FiberSolver()

    # ------------------------------
    # Collection / Proxy
    # ------------------------------

    def _get_vis_collection(self, scene):
        col = scene.collection.children.get(self.collection_name)
        if col is None:
            col = bpy.data.collections.new(self.collection_name)
            scene.collection.children.link(col)
        return col

    def _find_fiber_proxy(self, vis_col, root_name, fiber_id):
        for obj in vis_col.objects:
            if (
                obj.get("af_fiber_proxy")
                and obj.get("af_root_name") == root_name
                and obj.get("af_fiber_id") == fiber_id
            ):
                return obj
        return None

    def _ensure_fiber_material(self, obj):
        if obj.data is None or not hasattr(obj.data, "materials"):
            return None

        if obj.data.materials and obj.data.materials[0]:
            return obj.data.materials[0]

        mat_name = f"AF_FIBER_MAT_{obj.get('af_fiber_id', obj.name)}"
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            mat = bpy.data.materials.new(mat_name)
            mat.use_nodes = False

        obj.data.materials.clear()
        obj.data.materials.append(mat)
        return mat

    def _set_fiber_color(self, obj, color):
        mat = self._ensure_fiber_material(obj)
        if mat:
            mat.diffuse_color = color

    def _create_fiber_proxy(self, vis_col, root, fiber_id):
        curve = bpy.data.curves.new(f"AF_{fiber_id}_curve", type="CURVE")
        curve.dimensions = "3D"
        curve.resolution_u = 12

        obj = bpy.data.objects.new(f"AF_{fiber_id}", curve)
        obj["af_fiber_proxy"] = True
        obj["af_root_name"] = root.name
        obj["af_fiber_id"] = fiber_id
        obj["af_fiber_base_color"] = list(DEFAULT_FIBER_COLOR)

        obj.parent = root
        obj.matrix_parent_inverse = root.matrix_world.inverted()

        vis_col.objects.link(obj)
        self._set_fiber_color(obj, DEFAULT_FIBER_COLOR)
        return obj

    # ------------------------------
    # Curve update
    # ------------------------------

    def _update_curve_points(self, obj, points, thickness):
        curve = obj.data
        while curve.splines:
            curve.splines.remove(curve.splines[0])

        spline = curve.splines.new(type="POLY")
        spline.points.add(len(points) - 1)
        for i, p in enumerate(points):
            spline.points[i].co = (p.x, p.y, p.z, 1.0)

        curve.bevel_depth = max(0.0, float(thickness))
        curve.fill_mode = "FULL"

    # ------------------------------
    # Selection highlight
    # ------------------------------

    def _apply_selection_highlight(self, root, scene):
        active_id = root.af_vcp_system.active_vcp_id
        active_type = root.af_vcp_system.active_vcp_type

        for obj in scene.objects:
            if not obj.get("af_fiber_proxy"):
                continue
            if obj.get("af_root_name") != root.name:
                continue

            base = tuple(obj.get("af_fiber_base_color", DEFAULT_FIBER_COLOR))
            if active_type == "FIBER" and obj.get("af_fiber_id") == active_id:
                self._set_fiber_color(obj, SELECTED_FIBER_COLOR)
            else:
                self._set_fiber_color(obj, base)

    # ------------------------------
    # Public sync
    # ------------------------------

    def sync_root_to_scene(self, root=None, scene=None, bake=False):
        scene = scene or bpy.context.scene
        root = root or get_af_root(scene)
        if root is None:
            return
        if not hasattr(root, "af_vcp_system"):
            return

        vis_col = self._get_vis_collection(scene)
        depsgraph = bpy.context.evaluated_depsgraph_get()

        live_ids = set()

        for fiber in root.af_vcp_system.fibers:
            live_ids.add(fiber.id)

            obj = self._find_fiber_proxy(vis_col, root.name, fiber.id)
            if obj is None:
                obj = self._create_fiber_proxy(vis_col, root, fiber.id)

            points = self._solver.solve_points(
                root=root,
                fiber_prop=fiber,
                scene=scene,
                depsgraph=depsgraph,
                bake=bake,
            )
            if len(points) < 2:
                continue

            self._update_curve_points(obj, points, fiber.thickness)

        # Remove stale fiber proxies
        for obj in list(vis_col.objects):
            if obj.get("af_fiber_proxy") and obj.get("af_root_name") == root.name:
                if obj.get("af_fiber_id") not in live_ids:
                    bpy.data.objects.remove(obj, do_unlink=True)

        self._apply_selection_highlight(root, scene)


_FIBER_SYNC = None


def register_fiber_sync():
    global _FIBER_SYNC
    if _FIBER_SYNC is None:
        _FIBER_SYNC = FiberSceneSync()
    return _FIBER_SYNC


def unregister_fiber_sync():
    global _FIBER_SYNC
    _FIBER_SYNC = None
