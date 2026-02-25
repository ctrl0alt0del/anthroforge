import bpy
from math import exp
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from ..utils import get_af_root
from ..vcp.muscle_surface import (
    build_surface_data,
    validate_anchor_structure,
)


class MuscleSceneSync:
    def __init__(self, collection_name="AF_VCP_VIS"):
        self.collection_name = collection_name
        self._syncing = False

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

    def _find_inflation_ctrl(self, vis_col, root_name, muscle_id):
        for obj in vis_col.objects:
            if (
                obj.get("af_muscle_inflation_ctrl")
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

    def _create_inflation_ctrl(self, vis_col, root, muscle_id):
        obj = bpy.data.objects.new(f"AF_{muscle_id}_INFL_MAX", None)
        obj.empty_display_type = "SPHERE"
        obj.empty_display_size = 0.04
        obj["af_muscle_inflation_ctrl"] = True
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

    def _remove_inflation_ctrl(self, obj):
        bpy.data.objects.remove(obj, do_unlink=True)

    def _nearest_on_muscle_surface(self, muscle_obj, world_point):
        if muscle_obj is None or muscle_obj.type != "MESH" or muscle_obj.data is None:
            return None, None

        depsgraph = bpy.context.evaluated_depsgraph_get()
        try:
            bvh = BVHTree.FromObject(muscle_obj, depsgraph)
        except Exception:
            bvh = None
        if bvh is None:
            return None, None

        local = muscle_obj.matrix_world.inverted() @ world_point
        hit = bvh.find_nearest(local)
        if hit is None or hit[0] is None:
            return None, None

        co_local, n_local, _face, _dist = hit
        co_world = muscle_obj.matrix_world @ co_local
        n_world = (muscle_obj.matrix_world.to_3x3() @ n_local).normalized()
        return co_world, n_world

    def _falloff_weight(self, t, falloff_type):
        x = max(0.0, min(1.0, t))
        if falloff_type == "LINEAR":
            return 1.0 - x
        if falloff_type == "SMOOTHSTEP":
            s = x * x * (3.0 - 2.0 * x)
            return 1.0 - s
        # GAUSSIAN
        return exp(-4.0 * x * x)

    def _compute_vertex_normals(self, points):
        m = len(points)
        n = len(points[0]) if m > 0 else 0
        if m == 0 or n == 0:
            return []

        acc = Vector((0.0, 0.0, 0.0))
        cnt = 0
        for i in range(m):
            for j in range(n):
                acc += points[i][j]
                cnt += 1
        centroid = acc / max(1, cnt)

        normals = [[Vector((0.0, 0.0, 1.0)) for _ in range(n)] for _ in range(m)]

        for i in range(m):
            im1 = max(0, i - 1)
            ip1 = min(m - 1, i + 1)
            for j in range(n):
                jm1 = max(0, j - 1)
                jp1 = min(n - 1, j + 1)

                tv = points[ip1][j] - points[im1][j]
                tu = points[i][jp1] - points[i][jm1]
                nrm = tv.cross(tu)
                if nrm.length <= 1e-10:
                    nrm = points[i][j] - centroid
                if nrm.length <= 1e-10:
                    nrm = Vector((0.0, 0.0, 1.0))
                else:
                    nrm.normalize()
                normals[i][j] = nrm

        return normals

    def _apply_inflation_from_ctrl(self, ordered_points, muscle):
        if not muscle.inflation_enabled:
            return ordered_points

        amount = float(muscle.inflation_max_value)
        radius = max(1e-8, float(muscle.inflation_falloff_radius))
        if amount <= 0.0:
            return ordered_points

        ctrl = Vector(muscle.inflation_ctrl_world)
        falloff_type = muscle.inflation_falloff_type

        m = len(ordered_points)
        if m == 0:
            return ordered_points
        n = len(ordered_points[0])
        if n == 0:
            return ordered_points

        normals = self._compute_vertex_normals(ordered_points)
        out = [[p.copy() for p in row] for row in ordered_points]

        for i in range(m):
            for j in range(n):
                p = ordered_points[i][j]
                d = (p - ctrl).length
                t = d / radius
                if t > 1.0 and falloff_type != "GAUSSIAN":
                    continue
                w = self._falloff_weight(t, falloff_type)
                if w <= 1e-8:
                    continue
                out[i][j] = p + normals[i][j] * (amount * w)

        return out

    def _ensure_inflation_ctrl(self, vis_col, root, muscle, muscle_obj, ordered_points):
        ctrl = self._find_inflation_ctrl(vis_col, root.name, muscle.id)
        if ctrl is None:
            ctrl = self._create_inflation_ctrl(vis_col, root, muscle.id)

        # Initialize if not set yet
        if Vector(muscle.inflation_ctrl_world).length_squared == 0.0:
            m = len(ordered_points)
            n = len(ordered_points[0]) if m > 0 else 0
            if m > 0 and n > 0:
                ci = m // 2
                cj = n // 2
                init_p = ordered_points[ci][cj].copy()
                muscle.inflation_ctrl_world = (init_p.x, init_p.y, init_p.z)

        target = Vector(muscle.inflation_ctrl_world)
        snapped, _n = self._nearest_on_muscle_surface(muscle_obj, target)
        if snapped is not None:
            target = snapped
            muscle.inflation_ctrl_world = (target.x, target.y, target.z)

        ctrl.location = target
        return ctrl

    def sync_root_to_scene(self, root=None, scene=None):
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

                # Ensure gizmo exists / snapped before inflation
                self._ensure_inflation_ctrl(vis_col, root, muscle, obj, ordered_points)

                deformed_points = self._apply_inflation_from_ctrl(ordered_points, muscle)

                try:
                    verts, faces, _n = build_surface_data(
                        ordered_fiber_points=deformed_points,
                        closed_v=bool(muscle.closed_v),
                    )
                except Exception:
                    self._update_mesh(obj, [], [])
                    self._ensure_material(obj, active=(vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id))
                    continue

                self._update_mesh(obj, verts, faces)
                self._ensure_material(obj, active=(vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id))

            # Cleanup stale muscle proxies + controls
            for obj in list(vis_col.objects):
                if obj.get("af_root_name") != root.name:
                    continue

                if obj.get("af_muscle_proxy") and obj.get("af_muscle_id") not in live_muscle_ids:
                    self._remove_muscle_proxy(obj)
                    continue

                if obj.get("af_muscle_inflation_ctrl") and obj.get("af_muscle_id") not in live_muscle_ids:
                    self._remove_inflation_ctrl(obj)
                    continue
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

        changed = False

        self._syncing = True
        try:
            for upd in depsgraph.updates:
                obj = upd.id
                if not isinstance(obj, bpy.types.Object):
                    continue
                if not obj.get("af_muscle_inflation_ctrl"):
                    continue
                if obj.get("af_root_name") != root.name:
                    continue
                if vis_col.objects.get(obj.name) is None:
                    continue

                muscle_id = obj.get("af_muscle_id")
                muscle = next((m for m in root.af_vcp_system.muscles if m.id == muscle_id), None)
                if muscle is None:
                    continue

                # snap ctrl to nearest point on muscle surface
                muscle_obj = self._find_muscle_proxy(vis_col, root.name, muscle_id)
                if muscle_obj is None:
                    continue

                snapped, _n = self._nearest_on_muscle_surface(muscle_obj, obj.location.copy())
                if snapped is None:
                    continue

                obj.location = snapped
                new_loc = (snapped.x, snapped.y, snapped.z)
                if tuple(muscle.inflation_ctrl_world) != new_loc:
                    muscle.inflation_ctrl_world = new_loc
                    changed = True
        finally:
            self._syncing = False

        if changed:
            self.sync_root_to_scene(root=root, scene=scene)


_MUSCLE_SYNC = None


def register_muscle_sync():
    global _MUSCLE_SYNC
    if _MUSCLE_SYNC is None:
        _MUSCLE_SYNC = MuscleSceneSync()

    h = _MUSCLE_SYNC.on_depsgraph_update
    if h not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(h)

    return _MUSCLE_SYNC


def unregister_muscle_sync():
    global _MUSCLE_SYNC
    if _MUSCLE_SYNC is None:
        return

    h = _MUSCLE_SYNC.on_depsgraph_update
    if h in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(h)

    _MUSCLE_SYNC = None
