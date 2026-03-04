import bpy
from math import exp
from mathutils import Vector
from mathutils.bvhtree import BVHTree
import json

from ..utils import get_af_root
from ..vcp.muscle_surface import (
    build_surface_data,
    validate_anchor_structure,
    prepare_surface_rows,
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

    def _find_muscle_proxy(self, vis_col, root_name, muscle_id, surface_type="BASE"):
        for obj in vis_col.objects:
            if (
                obj.get("af_muscle_proxy")
                and obj.get("af_root_name") == root_name
                and obj.get("af_muscle_id") == muscle_id
                and obj.get("af_muscle_surface") == surface_type
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

    def _create_muscle_proxy(self, vis_col, root, muscle_id, surface_type):
        suffix = "" if surface_type == "BASE" else "_INFL"
        mesh = bpy.data.meshes.new(f"AF_{muscle_id}{suffix}_mesh")
        obj = bpy.data.objects.new(f"AF_{muscle_id}{suffix}", mesh)
        obj["af_muscle_proxy"] = True
        obj["af_root_name"] = root.name
        obj["af_muscle_id"] = muscle_id
        obj["af_muscle_surface"] = surface_type
        vis_col.objects.link(obj)
        return obj

    def _create_inflation_ctrl(self, vis_col, root, muscle_id):
        obj = bpy.data.objects.new(f"AF_{muscle_id}_INFL_MAX", None)
        obj.empty_display_type = "SPHERE"
        obj.empty_display_size = 0.04
        obj.show_in_front = True
        obj.hide_render = True
        obj["af_muscle_inflation_ctrl"] = True
        obj["af_root_name"] = root.name
        obj["af_muscle_id"] = muscle_id
        vis_col.objects.link(obj)
        return obj

    def _ensure_material(self, obj, active=False):
        if obj.data is None or not hasattr(obj.data, "materials"):
            return

        surf = obj.get("af_muscle_surface", "BASE")
        mat_name = f"AF_MUSCLE_MAT_{obj.get('af_muscle_id', obj.name)}_{surf}"
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            mat = bpy.data.materials.new(mat_name)
            mat.use_nodes = False

        if surf == "BASE":
            mat.diffuse_color = (0.35, 0.20, 0.18, 0.35) if not active else (0.45, 0.25, 0.22, 0.45)
        else:
            mat.diffuse_color = (0.80, 0.35, 0.30, 0.80) if active else (0.72, 0.42, 0.32, 0.65)

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
        from .fiber_sync import register_fiber_sync

        fsync = register_fiber_sync()
        vis_col = bpy.data.collections.get(fsync.collection_name)
        if vis_col is None:
            return None

        out = []
        for f in fiber_props:
            fobj = fsync._find_fiber_proxy(vis_col, root.name, f.id)
            if fobj is None:
                return None

            raw = fobj.get("af_fiber_points_world", "")
            if not raw:
                return None

            try:
                arr = json.loads(raw)
                pts = [Vector((float(v[0]), float(v[1]), float(v[2]))) for v in arr]
            except Exception:
                return None

            if len(pts) < 2:
                return None

            out.append(pts)

        return out

    def _remove_proxy_obj(self, obj):
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)

    def _remove_ctrl_obj(self, obj):
        bpy.data.objects.remove(obj, do_unlink=True)

    def _nearest_on_mesh_surface(self, mesh_obj, world_point):
        if mesh_obj is None or mesh_obj.type != "MESH" or mesh_obj.data is None:
            return None, None

        depsgraph = bpy.context.evaluated_depsgraph_get()
        try:
            bvh = BVHTree.FromObject(mesh_obj, depsgraph)
        except Exception:
            bvh = None
        if bvh is None:
            return None, None

        local = mesh_obj.matrix_world.inverted() @ world_point
        hit = bvh.find_nearest(local)
        if hit is None or hit[0] is None:
            return None, None

        co_local, n_local, _face_idx, _dist = hit
        co_world = mesh_obj.matrix_world @ co_local
        n_world = (mesh_obj.matrix_world.to_3x3() @ n_local).normalized()
        return co_world, n_world

    def _falloff_weight(self, t, falloff_type):
        x = max(0.0, min(1.0, t))
        if falloff_type == "LINEAR":
            return 1.0 - x
        if falloff_type == "SMOOTHSTEP":
            s = x * x * (3.0 - 2.0 * x)
            return 1.0 - s
        return exp(-4.0 * x * x)

    def _compute_vertex_normals(self, points):
        m = len(points)
        n = len(points[0]) if m > 0 else 0
        if m == 0 or n == 0:
            return []

        centroid = Vector((0.0, 0.0, 0.0))
        cnt = 0
        for i in range(m):
            for j in range(n):
                centroid += points[i][j]
                cnt += 1
        centroid /= max(1, cnt)

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

    def _apply_inflation_from_ctrl(self, base_points, muscle):
        out = [[p.copy() for p in row] for row in base_points]

        if not muscle.inflation_enabled:
            return out

        amount = float(muscle.inflation_max_value)
        radius = max(1e-8, float(muscle.inflation_falloff_radius))
        b_strength = max(0.0, min(1.0, float(getattr(muscle, "inflation_boundary_strength", 0.7))))
        b_band = max(0.1, float(getattr(muscle, "inflation_boundary_band", 2.0)))
        b_power = max(0.1, float(getattr(muscle, "inflation_boundary_power", 1.5)))

        L = max(1e-8, float(getattr(muscle, "inflation_direction_depth", 0.05)))
        if amount <= 0.0:
            return out

        m = len(base_points)
        n = len(base_points[0]) if m > 0 else 0
        if m == 0 or n == 0:
            return out

        ctrl = Vector(muscle.inflation_ctrl_world)
        falloff_type = muscle.inflation_falloff_type
        normals = self._compute_vertex_normals(base_points)

        flip = bool(getattr(muscle, "flip_normals", False))
        sign = -1.0 if flip else 1.0

        min_d2 = None
        ci = 0
        cj = 0
        for i in range(m):
            for j in range(n):
                d2 = (base_points[i][j] - ctrl).length_squared
                if min_d2 is None or d2 < min_d2:
                    min_d2 = d2
                    ci, cj = i, j

        n0 = normals[ci][cj].copy()
        if n0.length <= 1e-10:
            n0 = Vector((0.0, 0.0, 1.0))
        else:
            n0.normalize()

        G = ctrl - (n0 * L * sign)

        def is_boundary(i, j):
            on_u = (j == 0 or j == n - 1)
            on_v = (not bool(muscle.closed_v)) and (i == 0 or i == m - 1)
            return on_u or on_v

        def boundary_distance(i, j):
            du = min(j, n - 1 - j) if n > 1 else 0
            if bool(muscle.closed_v):
                dv = 10**9
            else:
                dv = min(i, m - 1 - i) if m > 1 else 0
            return min(du, dv)

        for i in range(m):
            for j in range(n):
                p = base_points[i][j]

                if is_boundary(i, j):
                    out[i][j] = p
                    continue

                d = (p - ctrl).length
                t = d / radius
                if falloff_type != "GAUSSIAN" and t > 1.0:
                    continue

                w = self._falloff_weight(t, falloff_type)
                if w <= 1e-8:
                    continue

                bd = boundary_distance(i, j)
                t_edge = max(0.0, min(1.0, bd / b_band))
                r = t_edge * t_edge * (3.0 - 2.0 * t_edge)
                r = r ** b_power
                edge_alpha = (1.0 - b_strength) + b_strength * r

                dir_vec = p - G
                if dir_vec.length <= 1e-10:
                    dir_vec = n0.copy()
                else:
                    dir_vec.normalize()

                out[i][j] = p + dir_vec * (amount * w * edge_alpha)

        return out

    def _ensure_inflation_ctrl(self, vis_col, root, muscle, base_obj, base_points):
        ctrl = self._find_inflation_ctrl(vis_col, root.name, muscle.id)
        if ctrl is None:
            ctrl = self._create_inflation_ctrl(vis_col, root, muscle.id)

        if Vector(muscle.inflation_ctrl_world).length_squared == 0.0:
            m = len(base_points)
            n = len(base_points[0]) if m > 0 else 0
            if m > 0 and n > 0:
                ci = m // 2
                cj = n // 2
                p = base_points[ci][cj]
                muscle.inflation_ctrl_world = (p.x, p.y, p.z)

        target = Vector(muscle.inflation_ctrl_world)
        snapped, _n = self._nearest_on_mesh_surface(base_obj, target)
        if snapped is not None:
            target = snapped
            muscle.inflation_ctrl_world = (target.x, target.y, target.z)

        ctrl.location = target
        ctrl.show_in_front = True
        ctrl.hide_render = True
        return ctrl

    def sync_root_to_scene(self, root=None, scene=None, target_muscle_ids=None):
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

            all_muscle_ids = {m.id for m in vcp.muscles}
            if target_muscle_ids is None:
                muscle_ids_to_sync = all_muscle_ids
            else:
                muscle_ids_to_sync = set(target_muscle_ids) & all_muscle_ids

            for muscle in vcp.muscles:
                if muscle.id not in muscle_ids_to_sync:
                    continue

                base_obj = self._find_muscle_proxy(vis_col, root.name, muscle.id, "BASE")
                if base_obj is None:
                    base_obj = self._create_muscle_proxy(vis_col, root, muscle.id, "BASE")

                infl_obj = self._find_muscle_proxy(vis_col, root.name, muscle.id, "INFL")
                if infl_obj is None:
                    infl_obj = self._create_muscle_proxy(vis_col, root, muscle.id, "INFL")

                ordered_fibers, missing = self._collect_fiber_props(root, muscle)
                if missing or len(ordered_fibers) < 2:
                    self._update_mesh(base_obj, [], [])
                    self._update_mesh(infl_obj, [], [])
                    active = (vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id)
                    self._ensure_material(base_obj, active=active)
                    self._ensure_material(infl_obj, active=active)
                    continue

                ok, _reason, _node_count, _anchors = validate_anchor_structure(ordered_fibers)
                if not ok:
                    self._update_mesh(base_obj, [], [])
                    self._update_mesh(infl_obj, [], [])
                    active = (vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id)
                    self._ensure_material(base_obj, active=active)
                    self._ensure_material(infl_obj, active=active)
                    continue

                ordered_points = self._collect_fiber_points(root, scene, ordered_fibers)
                if not ordered_points:
                    from .fiber_sync import register_fiber_sync
                    register_fiber_sync().sync_root_to_scene(
                        root=root,
                        scene=scene,
                        bake=False,
                        target_fiber_ids={f.id for f in ordered_fibers},
                    )
                    ordered_points = self._collect_fiber_points(root, scene, ordered_fibers)

                if not ordered_points:
                    self._update_mesh(base_obj, [], [])
                    self._update_mesh(infl_obj, [], [])
                    active = (vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id)
                    self._ensure_material(base_obj, active=active)
                    self._ensure_material(infl_obj, active=active)
                    continue

                base_points = prepare_surface_rows(
                    ordered_fiber_points=ordered_points,
                    target_n=int(ordered_fibers[0].node_count),
                    densify_v=True,
                )

                try:
                    base_verts, faces_raw, _n = build_surface_data(
                        ordered_fiber_points=base_points,
                        closed_v=bool(muscle.closed_v),
                    )
                except Exception:
                    self._update_mesh(base_obj, [], [])
                    self._update_mesh(infl_obj, [], [])
                    active = (vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id)
                    self._ensure_material(base_obj, active=active)
                    self._ensure_material(infl_obj, active=active)
                    continue

                flip = bool(getattr(muscle, "flip_normals", False))
                faces_final = [(f[0], f[3], f[2], f[1]) for f in faces_raw] if flip else faces_raw

                self._update_mesh(base_obj, base_verts, faces_final)
                self._ensure_inflation_ctrl(vis_col, root, muscle, base_obj, base_points)
                infl_points = self._apply_inflation_from_ctrl(base_points, muscle)

                try:
                    infl_verts, _faces_raw2, _n2 = build_surface_data(
                        ordered_fiber_points=infl_points,
                        closed_v=bool(muscle.closed_v),
                    )
                except Exception:
                    infl_verts = list(base_verts)

                self._update_mesh(infl_obj, infl_verts, faces_final)

                active = (vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id)
                self._ensure_material(base_obj, active=active)
                self._ensure_material(infl_obj, active=active)

            if target_muscle_ids is None:
                for obj in list(vis_col.objects):
                    if obj.get("af_root_name") != root.name:
                        continue

                    if obj.get("af_muscle_proxy") and obj.get("af_muscle_id") not in all_muscle_ids:
                        self._remove_proxy_obj(obj)
                        continue

                    if obj.get("af_muscle_inflation_ctrl") and obj.get("af_muscle_id") not in all_muscle_ids:
                        self._remove_ctrl_obj(obj)
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
        changed_muscle_ids = set()

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

                base_obj = self._find_muscle_proxy(vis_col, root.name, muscle_id, "BASE")
                if base_obj is None:
                    continue

                snapped, _n = self._nearest_on_mesh_surface(base_obj, obj.location.copy())
                if snapped is None:
                    continue

                obj.location = snapped
                new_loc = (snapped.x, snapped.y, snapped.z)
                if tuple(muscle.inflation_ctrl_world) != new_loc:
                    muscle.inflation_ctrl_world = new_loc
                    changed = True
                    changed_muscle_ids.add(muscle_id)

        finally:
            self._syncing = False

        if changed and changed_muscle_ids:
            from .sync_runner import sync_from_muscle_ids
            sync_from_muscle_ids(root=root, scene=scene, muscle_ids=changed_muscle_ids)


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
