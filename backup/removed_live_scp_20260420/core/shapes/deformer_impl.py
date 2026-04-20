from math import atan2, cos, radians, sin, sqrt
import bmesh
from mathutils import Vector

from .deformers import ShapeDeformer, DeformerUpdateRequest


class ParallelepipedBendDeformer(ShapeDeformer):
    deformer_id = "parallelepiped_bend"
    priority = 20

    @staticmethod
    def _axis_components(axis, p):
        if axis == "Y":
            return p.y, p.z, p.x
        if axis == "Z":
            return p.z, p.x, p.y
        return p.x, p.y, p.z

    @staticmethod
    def _axis_vector(axis, u, v, w):
        if axis == "Y":
            return Vector((w, u, v))
        if axis == "Z":
            return Vector((v, w, u))
        return Vector((u, v, w))

    def _bend_basis(self, p, shape, axis, deformer_state):
        u_center, span, v_center = self._runtime_bend_frame(shape, axis, deformer_state)
        u, v, w = self._axis_components(axis, p)
        return axis, u_center, span, v_center, u, v, w

    def _runtime_bend_frame(self, shape, axis, deformer_state):
        params = getattr(deformer_state, "params", {}) or {}
        k = str(axis or "X").upper()
        u_key = f"__frame_u_center_{k}"
        s_key = f"__frame_span_{k}"
        v_key = f"__frame_v_center_{k}"
        if u_key in params and s_key in params and v_key in params:
            return float(params[u_key]), max(1e-8, float(params[s_key])), float(params[v_key])
        return shape.bend_frame(axis)

    def extract_params(self, shape):
        return {
            "enabled": bool(getattr(shape, "bend_enabled", False)),
            "axis": str(getattr(shape, "bend_axis", "X")),
            "angle_deg": float(getattr(shape, "bend_angle_deg", 0.0)),
            "radius": float(getattr(shape, "bend_radius", 1.0)),
        }

    def prepare_state_from_domain(self, shape, deformer_state, domain_points):
        pts = list(domain_points or [])
        if not pts:
            return
        axis = str((deformer_state.params or {}).get("axis", getattr(shape, "bend_axis", "X")))
        us = []
        vs = []
        for p in pts:
            u, v, _w = self._axis_components(axis, p)
            us.append(float(u))
            vs.append(float(v))
        if not us:
            return
        u_min = min(us)
        u_max = max(us)
        span = max(1e-8, (u_max - u_min))
        u_center = 0.5 * (u_min + u_max)
        v_center = 0.5 * (min(vs) + max(vs)) if vs else 0.0
        k = str(axis or "X").upper()
        deformer_state.params[f"__frame_u_center_{k}"] = float(u_center)
        deformer_state.params[f"__frame_span_{k}"] = float(span)
        deformer_state.params[f"__frame_v_center_{k}"] = float(v_center)

    def forward_state(self, p, shape, deformer_state):
        params = dict(getattr(deformer_state, "params", {}) or {})
        if not bool(getattr(deformer_state, "enabled", True)):
            return p

        axis = str(params.get("axis", getattr(shape, "bend_axis", "X")))
        angle_rad = radians(float(params.get("angle_deg", getattr(shape, "bend_angle_deg", 0.0))))
        if abs(angle_rad) <= 1e-9:
            return p

        axis, u_center, span, v_center, u, v, w = self._bend_basis(p, shape, axis, deformer_state)
        theta = ((u - u_center) / span) * angle_rad
        r0 = max(1e-6, float(params.get("radius", getattr(shape, "bend_radius", 1.0))))
        v_local = v - v_center
        r = max(1e-6, r0 + v_local)
        new_u = u_center + (sin(theta) * r)
        new_v = v_center + ((cos(theta) * r) - r0)
        return self._axis_vector(axis, new_u, new_v, w)

    def inverse_state(self, p, shape, deformer_state):
        params = dict(getattr(deformer_state, "params", {}) or {})
        if not bool(getattr(deformer_state, "enabled", True)):
            return p.copy()

        axis = str(params.get("axis", getattr(shape, "bend_axis", "X")))
        angle_rad = radians(float(params.get("angle_deg", getattr(shape, "bend_angle_deg", 0.0))))
        if abs(angle_rad) <= 1e-9:
            return p.copy()

        axis, u_center, span, v_center, new_u, new_v, w = self._bend_basis(p, shape, axis, deformer_state)
        r0 = max(1e-6, float(params.get("radius", getattr(shape, "bend_radius", 1.0))))
        su = new_u - u_center
        cv = (new_v - v_center) + r0
        r = max(1e-6, sqrt((su * su) + (cv * cv)))
        theta = atan2(su, cv)
        u = u_center + (theta / angle_rad) * span
        v = v_center + (r - r0)
        return self._axis_vector(axis, u, v, w)


class ParallelepipedMirrorPairDeformer(ShapeDeformer):
    deformer_id = "parallelepiped_mirror_pair"
    priority = 12

    _PAIR_MAP = {
        "X": {0: 1, 1: 0, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6},
        "Y": {0: 3, 3: 0, 1: 2, 2: 1, 4: 7, 7: 4, 5: 6, 6: 5},
        "Z": {0: 4, 4: 0, 1: 5, 5: 1, 2: 6, 6: 2, 3: 7, 7: 3},
    }

    def request_handle_update(self, *, shape, proxy_obj, handle_world_location, vert_index, scp_prop):
        if not bool(getattr(shape, "is_mirror_source", lambda: False)()):
            return None

        axis = str(getattr(shape, "mirror_axis", lambda: "X")())
        pair_index = self._PAIR_MAP.get(axis, self._PAIR_MAP["X"]).get(int(vert_index), -1)
        if pair_index < 0:
            return None

        src_local_base = shape.world_handle_to_base_point(proxy_obj, handle_world_location)
        mirrored_local_base = src_local_base.copy()
        plane = 0.0
        if hasattr(shape, "mirror_source_plane_coord_local"):
            try:
                plane = float(shape.mirror_source_plane_coord_local(axis))
            except Exception:
                plane = 0.0
        if axis == "Y":
            mirrored_local_base.y = (2.0 * plane) - mirrored_local_base.y
        elif axis == "Z":
            mirrored_local_base.z = (2.0 * plane) - mirrored_local_base.z
        else:
            mirrored_local_base.x = (2.0 * plane) - mirrored_local_base.x
        return DeformerUpdateRequest(
            request_type="MIRROR_PAIR_POINT",
            payload={"pair_index": int(pair_index), "pair_local_base_point": mirrored_local_base},
        )


class EllipsoidClipDeformer(ShapeDeformer):
    deformer_id = "ellipsoid_clip"
    priority = 20

    def extract_params(self, shape):
        return {
            "enabled": bool(getattr(shape, "clip_enabled", False)),
            "clip1_enabled": bool(getattr(shape, "clip1_enabled", False)),
            "clip1_normal": tuple(getattr(shape, "clip1_normal", (1.0, 0.0, 0.0))),
            "clip1_offset": float(getattr(shape, "clip1_offset", 0.0)),
            "clip1_keep_side": str(getattr(shape, "clip1_keep_side", "POS")),
            "clip2_enabled": bool(getattr(shape, "clip2_enabled", False)),
            "clip2_normal": tuple(getattr(shape, "clip2_normal", (-1.0, 0.0, 0.0))),
            "clip2_offset": float(getattr(shape, "clip2_offset", 0.0)),
            "clip2_keep_side": str(getattr(shape, "clip2_keep_side", "POS")),
        }

    def forward_point(self, p, _shape):
        return p

    def inverse_point(self, p, _shape):
        return p

    @staticmethod
    def _bool_from_params(params, key, fallback):
        return bool(params.get(key, fallback))

    @staticmethod
    def _value(params, key, fallback):
        return params.get(key, fallback)

    def plane_defs(self, shape, deformer_state=None):
        params = dict(getattr(deformer_state, "params", {}) or {})
        enabled = bool(getattr(deformer_state, "enabled", True)) and self._bool_from_params(params, "enabled", getattr(shape, "clip_enabled", False))
        if not enabled:
            return []
        out = []
        for i in (1, 2):
            if not self._bool_from_params(params, f"clip{i}_enabled", getattr(shape, f"clip{i}_enabled", False)):
                continue
            n = Vector(self._value(params, f"clip{i}_normal", getattr(shape, f"clip{i}_normal", (1.0, 0.0, 0.0))))
            if n.length <= 1e-9:
                continue
            n.normalize()
            off = float(self._value(params, f"clip{i}_offset", getattr(shape, f"clip{i}_offset", 0.0)))
            keep_side = str(self._value(params, f"clip{i}_keep_side", getattr(shape, f"clip{i}_keep_side", "POS")))
            keep_pos = (keep_side != "NEG")
            out.append((n, off, keep_pos))
        return out

    def is_kept(self, p, shape, deformer_state=None):
        for n, off, keep_pos in self.plane_defs(shape, deformer_state=deformer_state):
            s = n.dot(p) - off
            if keep_pos:
                if s < 0.0:
                    return False
            else:
                if s > 0.0:
                    return False
        return True

    def project_to_boundary(self, p, shape, deformer_state=None):
        q = p.copy()
        for n, off, keep_pos in self.plane_defs(shape, deformer_state=deformer_state):
            s = n.dot(q) - off
            if keep_pos:
                if s < 0.0:
                    q -= n * s
            else:
                if s > 0.0:
                    q -= n * s
        return q

    def forward_state(self, p, shape, deformer_state):
        if not self.is_kept(p, shape, deformer_state=deformer_state):
            return self.project_to_boundary(p, shape, deformer_state=deformer_state)
        return p

    def apply_geometry_state(self, verts, faces, shape, deformer_state):
        out_verts = [v.copy() for v in list(verts or [])]
        out_faces = list(faces or [])
        planes = self.plane_defs(shape, deformer_state=deformer_state)
        if not planes:
            return out_verts, out_faces
        bm = bmesh.new()
        try:
            vmap = []
            for v in out_verts:
                vmap.append(bm.verts.new(v.copy()))
            bm.verts.ensure_lookup_table()
            for f in out_faces:
                try:
                    bm.faces.new([vmap[int(i)] for i in f])
                except Exception:
                    continue
            bm.faces.ensure_lookup_table()

            for n, off, keep_pos in planes:
                geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
                bmesh.ops.bisect_plane(
                    bm,
                    geom=geom,
                    plane_co=n * off,
                    plane_no=n,
                    clear_inner=bool(keep_pos),
                    clear_outer=not bool(keep_pos),
                    dist=1e-6,
                )
                boundary = [e for e in bm.edges if e.is_boundary]
                if boundary:
                    try:
                        bmesh.ops.holes_fill(bm, edges=boundary, sides=0)
                    except Exception:
                        pass

            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            idx_by_vert = {}
            out_verts = []
            for i, v in enumerate(bm.verts):
                idx_by_vert[v] = i
                out_verts.append(v.co.copy())
            out_faces = []
            for f in bm.faces:
                out_faces.append(tuple(idx_by_vert[v] for v in f.verts))
            return out_verts, out_faces
        finally:
            bm.free()
