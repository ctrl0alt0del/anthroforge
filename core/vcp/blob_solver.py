from mathutils import Vector

from ..scp_runtime.surface import surface_bvh_local


class BlobSolveResult:
    def __init__(self, points=None, converged=False, max_disp=0.0, iterations_used=0, patch_size=0):
        self.points = points or []
        self.converged = bool(converged)
        self.max_disp = float(max_disp)
        self.iterations_used = int(iterations_used)
        self.patch_size = int(patch_size)


class BlobSolver:
    """
    World-space blob solve.
    Hard clamp rule:
      For each vertex p, cast segment p -> control_point against target mesh.
      If hit exists before control point, set p = hit_point.
    """

    def __init__(self):
        pass

    def clear_cache(self, blob_id=None):
        return

    def _build_target_bvh(self, target_obj):
        if target_obj is None or target_obj.type != "MESH":
            return None
        try:
            return surface_bvh_local(target_obj)
        except Exception:
            return None

    def _nearest_surface_world(self, bvh, target_obj, world_point):
        if bvh is None or target_obj is None:
            return None, None

        local = target_obj.matrix_world.inverted() @ world_point
        hit = bvh.find_nearest(local)
        if hit is None or hit[0] is None:
            return None, None

        co_local, _n_local, _face_idx, _dist_local = hit
        co_world = target_obj.matrix_world @ co_local
        dist_world = (world_point - co_world).length
        return co_world, dist_world

    def _segment_hit_to_point(self, bvh, target_obj, p_world, q_world):
        if bvh is None or target_obj is None:
            return None

        m_inv = target_obj.matrix_world.inverted()
        p_local = m_inv @ p_world
        q_local = m_inv @ q_world

        v_local = q_local - p_local
        max_dist_local = v_local.length
        if max_dist_local <= 1e-10:
            return None

        d_local = v_local.normalized()
        hit = bvh.ray_cast(p_local, d_local, max_dist_local)
        if hit is None or hit[0] is None:
            return None

        co_local, _n_local, _face_idx, dist_local = hit
        if dist_local is None:
            return None
        if dist_local >= max_dist_local:
            return None

        return target_obj.matrix_world @ co_local

    def _build_adjacency(self, face_indices, vert_count):
        nbrs = [set() for _ in range(vert_count)]
        for f in face_indices:
            ln = len(f)
            if ln < 3:
                continue
            for i in range(ln):
                a = f[i]
                b = f[(i + 1) % ln]
                if 0 <= a < vert_count and 0 <= b < vert_count and a != b:
                    nbrs[a].add(b)
                    nbrs[b].add(a)
        return nbrs

    def _apply_viscosity(self, points, neighbors, alpha):
        if alpha <= 0.0:
            return
        alpha = max(0.0, min(1.0, float(alpha)))
        new_pts = [p.copy() for p in points]
        for i, p in enumerate(points):
            nbs = neighbors[i]
            if not nbs:
                continue
            c = Vector((0.0, 0.0, 0.0))
            for j in nbs:
                c += points[j]
            c /= len(nbs)
            new_pts[i] = p.lerp(c, alpha)
        for i in range(len(points)):
            points[i] = new_pts[i]

    def _init_solve_state(self, rest_world_verts):
        points = [p.copy() for p in rest_world_verts]
        rest = [p.copy() for p in rest_world_verts]
        prev = [p.copy() for p in points]
        return points, rest, prev

    def _solver_params(self, blob):
        iterations = max(1, int(getattr(blob, "iterations", 20)))
        sag_strength = max(0.0, float(getattr(blob, "sag_strength", 0.0)))
        stiffness = max(0.0, min(1.0, float(getattr(blob, "stiffness", 0.25))))
        sag_limit = max(0.0, float(getattr(blob, "sag_limit", 0.0)))

        g = Vector(blob.gravity_dir)
        if g.length <= 1e-10:
            g = Vector((0.0, 0.0, -1.0))
        else:
            g.normalize()

        return {
            "iterations": iterations,
            "eps": 1e-6,
            "g": g,
            "sag_limit": sag_limit,
            "base_gravity": 0.002 * sag_strength,
            "dist_gravity_k": 0.02 * sag_strength,
            "viscosity_alpha": (1.0 - stiffness) * 0.18,
        }

    def _apply_gravity(self, points, bvh, target_obj, params):
        g = params["g"]
        base_gravity = params["base_gravity"]
        dist_gravity_k = params["dist_gravity_k"]
        sag_limit = params["sag_limit"]
        for i, p in enumerate(points):
            _co, d = self._nearest_surface_world(bvh, target_obj, p)
            if d is None:
                continue
            step = base_gravity + dist_gravity_k * d
            if sag_limit > 0.0:
                step = min(step, sag_limit * 0.25)
            points[i] = p + g * step

    def _project_to_control_segment(self, points, bvh, target_obj, control):
        for i, p in enumerate(points):
            hit_world = self._segment_hit_to_point(bvh=bvh, target_obj=target_obj, p_world=p, q_world=control)
            if hit_world is not None:
                points[i] = hit_world

    def _apply_sag_limit(self, points, rest, params):
        sag_limit = params["sag_limit"]
        if sag_limit <= 0.0:
            return
        g = params["g"]
        for i in range(len(points)):
            drop = (points[i] - rest[i]).dot(g)
            if drop > sag_limit:
                points[i] -= g * (drop - sag_limit)

    def _max_disp_and_store_prev(self, points, prev):
        max_disp = 0.0
        for i in range(len(points)):
            d = (points[i] - prev[i]).length
            if d > max_disp:
                max_disp = d
            prev[i] = points[i].copy()
        return max_disp

    def solve(self, blob, target_obj, rest_world_verts, face_indices):
        if not rest_world_verts:
            return BlobSolveResult(points=[])
        points, rest, prev = self._init_solve_state(rest_world_verts)
        bvh = self._build_target_bvh(target_obj)
        if bvh is None or target_obj is None:
            return self._early_result(points)
        neighbors = self._build_adjacency(face_indices, len(points))
        params = self._solver_params(blob)
        converged, max_disp, it_used = self._iterate(points, rest, prev, bvh, target_obj, neighbors, params, blob)
        return BlobSolveResult(points=points, converged=converged, max_disp=max_disp, iterations_used=it_used, patch_size=0)

    def _early_result(self, points):
        return BlobSolveResult(points=points, converged=True, max_disp=0.0, iterations_used=1, patch_size=0)

    def _iterate(self, points, rest, prev, bvh, target_obj, neighbors, params, blob):
        converged = False
        max_disp = 0.0
        it_used = 0
        for it in range(params["iterations"]):
            it_used = it + 1
            self._step(points, rest, prev, bvh, target_obj, neighbors, params, blob.control_point_world.copy())
            max_disp = self._max_disp_and_store_prev(points, prev)
            if max_disp < params["eps"]:
                converged = True
                break
        return converged, max_disp, it_used

    def _step(self, points, rest, prev, bvh, target_obj, neighbors, params, control):
        self._apply_gravity(points, bvh, target_obj, params)
        self._apply_viscosity(points, neighbors, params["viscosity_alpha"])
        self._project_to_control_segment(points, bvh, target_obj, control)
        self._apply_sag_limit(points, rest, params)
