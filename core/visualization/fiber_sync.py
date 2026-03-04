import json
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras import view3d_utils

from ..utils import get_af_root
from ..vcp.fiber_solver import FiberSolver
from ..registry import SCPRegistry

DEFAULT_FIBER_COLOR = (0.85, 0.55, 0.20, 1.0)
SELECTED_FIBER_COLOR = (1.0, 0.0, 0.0, 1.0)


class FiberSceneSync:
    def __init__(self, collection_name="AF_VCP_VIS"):
        self.collection_name = collection_name
        self._solver = FiberSolver(surface_offset=0.002)
        self._syncing = False

    def clear_solver_cache(self, fiber_id=None):
        self._solver.clear_cache(fiber_id)

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
                and not obj.get("af_fiber_mirror_proxy")
                and obj.get("af_root_name") == root_name
                and obj.get("af_fiber_id") == fiber_id
            ):
                return obj
        return None

    def _find_endpoint_handle(self, vis_col, root_name, fiber_id, endpoint):
        for obj in vis_col.objects:
            if (
                obj.get("af_fiber_endpoint_handle")
                and obj.get("af_root_name") == root_name
                and obj.get("af_fiber_id") == fiber_id
                and obj.get("af_fiber_endpoint") == endpoint
            ):
                return obj
        return None

    def _find_touch_handle(self, vis_col, root_name, fiber_id, touch_index):
        for obj in vis_col.objects:
            if (
                obj.get("af_fiber_touch_handle")
                and obj.get("af_root_name") == root_name
                and obj.get("af_fiber_id") == fiber_id
                and int(obj.get("af_fiber_touch_index", -1)) == int(touch_index)
            ):
                return obj
        return None

    def _create_endpoint_handle(self, vis_col, root, fiber_id, endpoint):
        obj = bpy.data.objects.new(f"AF_{fiber_id}_{endpoint}", None)
        obj.empty_display_type = "SPHERE"
        obj.empty_display_size = 0.035
        obj.show_in_front = True
        obj.hide_render = True
        obj["af_fiber_endpoint_handle"] = True
        obj["af_root_name"] = root.name
        obj["af_fiber_id"] = fiber_id
        obj["af_fiber_endpoint"] = endpoint
        vis_col.objects.link(obj)
        return obj

    def _create_touch_handle(self, vis_col, root, fiber_id, touch_index):
        obj = bpy.data.objects.new(f"AF_{fiber_id}_T{touch_index}", None)
        obj.empty_display_type = "CUBE"
        obj.empty_display_size = 0.03
        obj.show_in_front = True
        obj.hide_render = True
        obj["af_fiber_touch_handle"] = True
        obj["af_root_name"] = root.name
        obj["af_fiber_id"] = fiber_id
        obj["af_fiber_touch_index"] = int(touch_index)
        vis_col.objects.link(obj)
        return obj

    def _ensure_fiber_material(self, obj):
        if obj.data is None or not hasattr(obj.data, "materials"):
            return None
        if obj.data.materials and obj.data.materials[0]:
            return obj.data.materials[0]
        mat = bpy.data.materials.get(f"AF_FIBER_MAT_{obj.get('af_fiber_id', obj.name)}")
        if mat is None:
            mat = bpy.data.materials.new(f"AF_FIBER_MAT_{obj.get('af_fiber_id', obj.name)}")
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
        obj = bpy.data.objects.new(f"AF_{fiber_id}", curve)
        obj["af_fiber_proxy"] = True
        obj["af_root_name"] = root.name
        obj["af_fiber_id"] = fiber_id
        obj["af_fiber_base_color"] = list(DEFAULT_FIBER_COLOR)
        vis_col.objects.link(obj)
        self._set_fiber_color(obj, DEFAULT_FIBER_COLOR)
        return obj

    def _update_curve_points(self, obj, points, thickness, bake=False):
        curve = obj.data
        while curve.splines:
            curve.splines.remove(curve.splines[0])

        spline = curve.splines.new(type="POLY")
        spline.points.add(len(points) - 1)
        for i, p in enumerate(points):
            spline.points[i].co = (p.x, p.y, p.z, 1.0)

        curve.bevel_depth = max(0.0, float(thickness))
        curve.fill_mode = "FULL"

        obj["af_fiber_points_world"] = json.dumps([[float(p.x), float(p.y), float(p.z)] for p in points])
        obj["af_fiber_points_mode"] = "BAKE" if bake else "INTERACTIVE"

    def _get_scp_proxy(self, scene, root_name, scp_id):
        for obj in scene.objects:
            if (
                obj.get("af_proxy")
                and not obj.get("af_mirror_proxy")
                and obj.get("af_root_name") == root_name
                and obj.get("af_scp_id") == scp_id
            ):
                return obj
        return None

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

    def _endpoint_world(self, root, scene, runtime_registry, parent_id, attach_param_raw):
        if not parent_id:
            return None

        scp = runtime_registry.get(parent_id)
        if scp is None:
            return None

        proxy = self._get_scp_proxy(scene, root.name, parent_id)
        if proxy is None:
            return None

        mode, payload = self._decode_attach_param(attach_param_raw)
        if mode == "mesh_anchor":
            local = payload
        else:
            local = scp.shape.compute_local_point(payload)

        return proxy.matrix_world @ local

    def _nearest_param(self, parent_scp, parent_proxy, moved_world):
        params = parent_scp.shape.get_attach_params()
        if not params:
            return 0.0
        best = params[0]
        best_d2 = None
        for p in params:
            w = parent_proxy.matrix_world @ parent_scp.shape.compute_local_point(p)
            d2 = (w - moved_world).length_squared
            if best_d2 is None or d2 < best_d2:
                best_d2 = d2
                best = p
        return best

    def _nearest_parent_mesh_local_point(self, parent_proxy, moved_world):
        if parent_proxy is None or parent_proxy.type != "MESH":
            return None
        depsgraph = bpy.context.evaluated_depsgraph_get()
        try:
            bvh = BVHTree.FromObject(parent_proxy, depsgraph)
        except Exception:
            return None
        if bvh is None:
            return None

        moved_local = parent_proxy.matrix_world.inverted() @ moved_world
        hit = bvh.find_nearest(moved_local)
        if hit is None or hit[0] is None:
            return None
        return hit[0].copy()

    def _get_active_view3d_region(self):
        wm = bpy.context.window_manager
        for win in wm.windows:
            screen = win.screen
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                rv3d = None
                for sp in area.spaces:
                    if sp.type == "VIEW_3D":
                        rv3d = sp.region_3d
                        break
                if rv3d is None:
                    continue
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                if region is None:
                    continue
                return region, rv3d
        return None, None

    def _world_units_per_pixel(self, world_loc):
        region, rv3d = self._get_active_view3d_region()
        if region is None or rv3d is None:
            return None

        p2d = view3d_utils.location_3d_to_region_2d(region, rv3d, world_loc)
        if p2d is None:
            return None

        p2d_2 = Vector((p2d.x + 1.0, p2d.y))
        w2 = view3d_utils.region_2d_to_location_3d(region, rv3d, p2d_2, world_loc)
        return (w2 - world_loc).length

    def _set_helper_screen_size(self, obj, px=14.0, min_size=0.005, max_size=0.25):
        wupp = self._world_units_per_pixel(obj.location)
        if wupp is None:
            return
        obj.empty_display_size = max(min_size, min(max_size, px * wupp))

    def _sync_handles(self, root, scene, vis_col, runtime_registry):
        live_endpoint_keys = set()
        live_touch_keys = set()

        for fiber in root.af_vcp_system.fibers:
            for endpoint, pid, raw in (
                ("A", fiber.a_parent_id, fiber.a_attach_param),
                ("B", fiber.b_parent_id, fiber.b_attach_param),
            ):
                live_endpoint_keys.add((fiber.id, endpoint))
                h = self._find_endpoint_handle(vis_col, root.name, fiber.id, endpoint)
                if h is None:
                    h = self._create_endpoint_handle(vis_col, root, fiber.id, endpoint)
                w = self._endpoint_world(root, scene, runtime_registry, pid, raw)
                if w is not None:
                    h.location = w
                    self._set_helper_screen_size(h, px=14.0)

            for i, tp in enumerate(fiber.mid_touches):
                live_touch_keys.add((fiber.id, i))
                h = self._find_touch_handle(vis_col, root.name, fiber.id, i)
                if h is None:
                    h = self._create_touch_handle(vis_col, root, fiber.id, i)

                w = self._endpoint_world(root, scene, runtime_registry, tp.parent_id, tp.attach_param)
                if w is not None:
                    h.location = w
                    self._set_helper_screen_size(h, px=12.0)

        for obj in list(vis_col.objects):
            if obj.get("af_fiber_endpoint_handle") and obj.get("af_root_name") == root.name:
                key = (obj.get("af_fiber_id"), obj.get("af_fiber_endpoint"))
                if key not in live_endpoint_keys:
                    bpy.data.objects.remove(obj, do_unlink=True)

            if obj.get("af_fiber_touch_handle") and obj.get("af_root_name") == root.name:
                key = (obj.get("af_fiber_id"), int(obj.get("af_fiber_touch_index", -1)))
                if key not in live_touch_keys:
                    bpy.data.objects.remove(obj, do_unlink=True)

    def _apply_selection_highlight(self, root, scene):
        active_id = root.af_vcp_system.active_vcp_id
        active_type = root.af_vcp_system.active_vcp_type
        for obj in scene.objects:
            if not obj.get("af_fiber_proxy"):
                continue
            if obj.get("af_root_name") != root.name:
                continue
            base = tuple(obj.get("af_fiber_base_color", DEFAULT_FIBER_COLOR))
            self._set_fiber_color(obj, SELECTED_FIBER_COLOR if active_type == "FIBER" and obj.get("af_fiber_id") == active_id else base)

    def sync_root_to_scene(self, root=None, scene=None, bake=False, target_fiber_ids=None):
        if self._syncing:
            return
        scene = scene or bpy.context.scene
        root = root or get_af_root(scene)
        if root is None or not hasattr(root, "af_vcp_system"):
            return

        self._syncing = True
        try:
            vis_col = self._get_vis_collection(scene)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            runtime = SCPRegistry(root)
            runtime.build()

            if target_fiber_ids is None:
                fibers_to_sync = list(root.af_vcp_system.fibers)
            else:
                target_set = set(target_fiber_ids)
                fibers_to_sync = [f for f in root.af_vcp_system.fibers if f.id in target_set]

            live_ids = set()
            for fiber in fibers_to_sync:
                live_ids.add(fiber.id)
                obj = self._find_fiber_proxy(vis_col, root.name, fiber.id)
                if obj is None:
                    obj = self._create_fiber_proxy(vis_col, root, fiber.id)

                points = self._solver.solve_points(root=root, fiber_prop=fiber, scene=scene, depsgraph=depsgraph, bake=bake)
                if len(points) >= 2:
                    self._update_curve_points(obj, points, fiber.thickness, bake=bake)

            if target_fiber_ids is None:
                for obj in list(vis_col.objects):
                    if (
                        obj.get("af_fiber_proxy")
                        and obj.get("af_root_name") == root.name
                        and obj.get("af_fiber_id") not in live_ids
                    ):
                        bpy.data.objects.remove(obj, do_unlink=True)

            self._sync_handles(root, scene, vis_col, runtime.registry)
            self._apply_selection_highlight(root, scene)
        finally:
            self._syncing = False

    def on_depsgraph_update(self, scene, depsgraph):
        if self._syncing:
            return
        root = get_af_root(scene)
        if root is None or not hasattr(root, "af_vcp_system"):
            return

        vis_col = bpy.data.collections.get(self.collection_name)
        if vis_col is None:
            return

        runtime = SCPRegistry(root)
        runtime.build()

        changed = False
        changed_fiber_ids = set()

        self._syncing = True
        try:
            for upd in depsgraph.updates:
                obj = upd.id
                if not isinstance(obj, bpy.types.Object):
                    continue
                if obj.get("af_root_name") != root.name:
                    continue
                if vis_col.objects.get(obj.name) is None:
                    continue

                if obj.get("af_fiber_endpoint_handle"):
                    fiber_id = obj.get("af_fiber_id")
                    endpoint = obj.get("af_fiber_endpoint")
                    fiber = next((f for f in root.af_vcp_system.fibers if f.id == fiber_id), None)
                    if fiber is None:
                        continue

                    parent_id = fiber.a_parent_id if endpoint == "A" else fiber.b_parent_id
                    parent_scp = runtime.registry.get(parent_id)
                    parent_proxy = self._get_scp_proxy(scene, root.name, parent_id)
                    if parent_scp is None or parent_proxy is None:
                        continue

                    local_pt = self._nearest_parent_mesh_local_point(parent_proxy, obj.location.copy())
                    if local_pt is not None:
                        raw = self._encode_mesh_anchor(local_pt)
                    else:
                        param = self._nearest_param(parent_scp, parent_proxy, obj.location.copy())
                        raw = json.dumps(param)

                    if endpoint == "A":
                        if fiber.a_attach_param != raw:
                            fiber.a_attach_param = raw
                            changed = True
                            changed_fiber_ids.add(fiber.id)
                    else:
                        if fiber.b_attach_param != raw:
                            fiber.b_attach_param = raw
                            changed = True
                            changed_fiber_ids.add(fiber.id)

                elif obj.get("af_fiber_touch_handle"):
                    fiber_id = obj.get("af_fiber_id")
                    touch_index = int(obj.get("af_fiber_touch_index", -1))
                    fiber = next((f for f in root.af_vcp_system.fibers if f.id == fiber_id), None)
                    if fiber is None:
                        continue
                    if touch_index < 0 or touch_index >= len(fiber.mid_touches):
                        continue

                    tp = fiber.mid_touches[touch_index]
                    parent_id = tp.parent_id
                    parent_scp = runtime.registry.get(parent_id)
                    parent_proxy = self._get_scp_proxy(scene, root.name, parent_id)
                    if parent_scp is None or parent_proxy is None:
                        continue

                    local_pt = self._nearest_parent_mesh_local_point(parent_proxy, obj.location.copy())
                    if local_pt is not None:
                        raw = self._encode_mesh_anchor(local_pt)
                    else:
                        param = self._nearest_param(parent_scp, parent_proxy, obj.location.copy())
                        raw = json.dumps(param)

                    if tp.attach_param != raw:
                        tp.attach_param = raw
                        changed = True
                        changed_fiber_ids.add(fiber.id)
        finally:
            self._syncing = False

        if changed:
            self.sync_root_to_scene(root=root, scene=scene, target_fiber_ids=changed_fiber_ids)
            from .muscle_sync import register_muscle_sync
            register_muscle_sync().sync_root_to_scene(root=root, scene=scene)


_FIBER_SYNC = None


def register_fiber_sync():
    global _FIBER_SYNC
    if _FIBER_SYNC is None:
        _FIBER_SYNC = FiberSceneSync()
    h = _FIBER_SYNC.on_depsgraph_update
    if h not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(h)
    return _FIBER_SYNC


def unregister_fiber_sync():
    global _FIBER_SYNC
    if _FIBER_SYNC is None:
        return
    h = _FIBER_SYNC.on_depsgraph_update
    if h in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(h)
    _FIBER_SYNC = None
