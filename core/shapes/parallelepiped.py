import bpy
from mathutils import Vector

from .base import ShapeStrategy
from .deformer_impl import ParallelepipedBendDeformer, ParallelepipedMirrorPairDeformer
from .deformers import ResolutionDeformer
from .registry import ShapeRegistry


class ParallelepipedShape(ShapeStrategy):
    type_id = "PARALLELEPIPED"
    label = "Parallelepiped"

    proxy_object_type = "MESH"
    proxy_data_type = "MESH"
    supports_fiber_collision = True

    _MIRROR_PAIR = ParallelepipedMirrorPairDeformer()
    _BEND = ParallelepipedBendDeformer()
    _RES = ResolutionDeformer()
    _SURFACE_FACES = ("X_MIN", "X_MAX", "Y_MIN", "Y_MAX", "Z_MIN", "Z_MAX")

    def __init__(
        self,
        size=(1.0, 1.0, 1.0),
        points=None,
        bend_enabled=False,
        bend_axis="X",
        bend_angle_deg=0.0,
        bend_radius=1.0,
        resolution=4,
    ):
        self.size = tuple(float(v) for v in size)
        self.points = points or self._default_points(self.size)
        self.bend_enabled = bool(bend_enabled)
        self.bend_axis = str(bend_axis or "X")
        self.bend_angle_deg = float(bend_angle_deg)
        self.bend_radius = float(bend_radius)
        self.resolution = max(1, int(resolution))

    def get_deformers(self):
        # Priority: mirror pair request -> bend -> resolution
        return [self._MIRROR_PAIR, self._BEND, self._RES]

    @staticmethod
    def _default_points(size):
        sx = float(size[0]) * 0.5
        sy = float(size[1]) * 0.5
        sz = float(size[2]) * 0.5
        return [
            Vector((-sx, -sy, -sz)),
            Vector(( sx, -sy, -sz)),
            Vector(( sx,  sy, -sz)),
            Vector((-sx,  sy, -sz)),
            Vector((-sx, -sy,  sz)),
            Vector(( sx, -sy,  sz)),
            Vector(( sx,  sy,  sz)),
            Vector((-sx,  sy,  sz)),
        ]

    @classmethod
    def _points_from_prop(cls, scp_prop):
        pts = [Vector((p.co[0], p.co[1], p.co[2])) for p in scp_prop.parallelepiped_points]
        if len(pts) != 8:
            return cls._default_points(scp_prop.parallelepiped_size)
        return pts

    @classmethod
    def from_scp_prop(cls, scp_prop):
        return cls(
            size=tuple(scp_prop.parallelepiped_size),
            points=cls._points_from_prop(scp_prop),
            bend_enabled=bool(getattr(scp_prop, "parallelepiped_bend_enabled", False)),
            bend_axis=getattr(scp_prop, "parallelepiped_bend_axis", "X"),
            bend_angle_deg=float(getattr(scp_prop, "parallelepiped_bend_angle_deg", 0.0)),
            bend_radius=float(getattr(scp_prop, "parallelepiped_bend_radius", 1.0)),
            resolution=int(getattr(scp_prop, "parallelepiped_resolution", 4)),
        )

    @classmethod
    def init_scp_prop_defaults(cls, scp_prop):
        scp_prop.parallelepiped_size = (1.0, 1.0, 1.0)
        scp_prop.parallelepiped_bend_enabled = False
        scp_prop.parallelepiped_bend_axis = "X"
        scp_prop.parallelepiped_bend_angle_deg = 0.0
        scp_prop.parallelepiped_bend_radius = 1.0
        scp_prop.parallelepiped_resolution = 4
        while len(scp_prop.parallelepiped_points) > 0:
            scp_prop.parallelepiped_points.remove(len(scp_prop.parallelepiped_points) - 1)
        for co in cls._default_points(scp_prop.parallelepiped_size):
            p = scp_prop.parallelepiped_points.add()
            p.co = (co.x, co.y, co.z)

    @classmethod
    def register_scene_props(cls):
        bpy.types.Scene.af_new_parallelepiped_size = bpy.props.FloatVectorProperty(
            name="Size", size=3, subtype="XYZ", default=(1.0, 1.0, 1.0), min=0.001
        )
        bpy.types.Scene.af_new_parallelepiped_bend_enabled = bpy.props.BoolProperty(
            name="Enable Bend", default=False
        )
        bpy.types.Scene.af_new_parallelepiped_bend_axis = bpy.props.EnumProperty(
            name="Bend Axis",
            items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")],
            default="X",
        )
        bpy.types.Scene.af_new_parallelepiped_bend_angle_deg = bpy.props.FloatProperty(
            name="Bend Angle (deg)",
            default=0.0,
            min=-360.0,
            max=360.0,
        )
        bpy.types.Scene.af_new_parallelepiped_bend_radius = bpy.props.FloatProperty(
            name="Bend Radius",
            default=1.0,
            min=0.001,
        )
        bpy.types.Scene.af_new_parallelepiped_resolution = bpy.props.IntProperty(
            name="Resolution",
            default=4,
            min=1,
            max=64,
        )

    @classmethod
    def unregister_scene_props(cls):
        if hasattr(bpy.types.Scene, "af_new_parallelepiped_size"):
            del bpy.types.Scene.af_new_parallelepiped_size
        if hasattr(bpy.types.Scene, "af_new_parallelepiped_bend_enabled"):
            del bpy.types.Scene.af_new_parallelepiped_bend_enabled
        if hasattr(bpy.types.Scene, "af_new_parallelepiped_bend_axis"):
            del bpy.types.Scene.af_new_parallelepiped_bend_axis
        if hasattr(bpy.types.Scene, "af_new_parallelepiped_bend_angle_deg"):
            del bpy.types.Scene.af_new_parallelepiped_bend_angle_deg
        if hasattr(bpy.types.Scene, "af_new_parallelepiped_bend_radius"):
            del bpy.types.Scene.af_new_parallelepiped_bend_radius
        if hasattr(bpy.types.Scene, "af_new_parallelepiped_resolution"):
            del bpy.types.Scene.af_new_parallelepiped_resolution

    @classmethod
    def draw_creation_ui(cls, layout, scene):
        layout.prop(scene, "af_new_parallelepiped_size")
        layout.prop(scene, "af_new_parallelepiped_bend_enabled")
        bcol = layout.column()
        bcol.enabled = bool(scene.af_new_parallelepiped_bend_enabled)
        bcol.prop(scene, "af_new_parallelepiped_bend_axis")
        bcol.prop(scene, "af_new_parallelepiped_bend_angle_deg")
        bcol.prop(scene, "af_new_parallelepiped_bend_radius")
        layout.prop(scene, "af_new_parallelepiped_resolution")

    @classmethod
    def apply_creation_to_scp(cls, scene, scp_prop):
        scp_prop.parallelepiped_size = scene.af_new_parallelepiped_size
        scp_prop.parallelepiped_bend_enabled = bool(scene.af_new_parallelepiped_bend_enabled)
        scp_prop.parallelepiped_bend_axis = scene.af_new_parallelepiped_bend_axis
        scp_prop.parallelepiped_bend_angle_deg = float(scene.af_new_parallelepiped_bend_angle_deg)
        scp_prop.parallelepiped_bend_radius = float(scene.af_new_parallelepiped_bend_radius)
        scp_prop.parallelepiped_resolution = int(scene.af_new_parallelepiped_resolution)
        while len(scp_prop.parallelepiped_points) > 0:
            scp_prop.parallelepiped_points.remove(len(scp_prop.parallelepiped_points) - 1)
        for co in cls._default_points(scp_prop.parallelepiped_size):
            p = scp_prop.parallelepiped_points.add()
            p.co = (co.x, co.y, co.z)

    @classmethod
    def draw_scp_ui(cls, layout, scp_prop, readonly=False):
        col = layout.column()
        col.enabled = not readonly
        col.prop(scp_prop, "parallelepiped_size")
        col.prop(scp_prop, "parallelepiped_bend_enabled")
        bcol = col.column()
        bcol.enabled = bool(scp_prop.parallelepiped_bend_enabled)
        bcol.prop(scp_prop, "parallelepiped_bend_axis")
        bcol.prop(scp_prop, "parallelepiped_bend_angle_deg")
        bcol.prop(scp_prop, "parallelepiped_bend_radius")
        col.prop(scp_prop, "parallelepiped_resolution")

        box = col.box()
        box.label(text="Vertices")
        for i, p in enumerate(scp_prop.parallelepiped_points):
            row = box.row(align=True)
            row.label(text=f"V{i}")
            row.prop(p, "co", text="")

    def _uvw_from_surface_param(self, param):
        if not isinstance(param, dict):
            return None
        if str(param.get("mode", "")) != "surface_uv":
            return None

        face = str(param.get("face", "X_MIN"))
        su = max(0.0, min(1.0, float(param.get("u", 0.5))))
        sv = max(0.0, min(1.0, float(param.get("v", 0.5))))

        if face == "X_MIN":
            return 0.0, su, sv
        if face == "X_MAX":
            return 1.0, su, sv
        if face == "Y_MIN":
            return su, 0.0, sv
        if face == "Y_MAX":
            return su, 1.0, sv
        if face == "Z_MIN":
            return su, sv, 0.0
        if face == "Z_MAX":
            return su, sv, 1.0
        return None

    def _surface_point(self, face, su, sv):
        if face == "X_MIN":
            p = self._trilinear_point(0.0, su, sv)
        elif face == "X_MAX":
            p = self._trilinear_point(1.0, su, sv)
        elif face == "Y_MIN":
            p = self._trilinear_point(su, 0.0, sv)
        elif face == "Y_MAX":
            p = self._trilinear_point(su, 1.0, sv)
        elif face == "Z_MIN":
            p = self._trilinear_point(su, sv, 0.0)
        else:
            p = self._trilinear_point(su, sv, 1.0)
        return self.apply_point_deformers(p)

    def get_attach_params(self):
        # Dense surface samples to avoid corner-only snapping.
        grid = max(6, int(self.resolution) * 2)
        params = []
        for face in self._SURFACE_FACES:
            for i in range(grid + 1):
                for j in range(grid + 1):
                    params.append(
                        {
                            "mode": "surface_uv",
                            "face": face,
                            "u": i / float(grid),
                            "v": j / float(grid),
                        }
                    )
        # Keep explicit per-vertex params synchronized with size.
        params.extend(list(range(len(self.points))))
        return params

    def compute_local_point(self, param):
        uvw = self._uvw_from_surface_param(param)
        if uvw is not None:
            u, v, w = uvw
            return self.apply_point_deformers(self._trilinear_point(u, v, w))

        try:
            idx = int(param)
        except Exception:
            idx = 0
        if not self.points:
            return Vector((0.0, 0.0, 0.0))
        idx = max(0, min(len(self.points) - 1, idx))
        return self.apply_point_deformers(self.points[idx].copy())

    def sample_attachment_frame_local(self, param):
        if isinstance(param, dict) and str(param.get("mode", "")) == "surface_uv":
            return self._surface_attachment_frame(param)
        return self._vertex_attachment_frame(param)

    def _surface_attachment_frame(self, param):
        face = str(param.get("face", "X_MIN"))
        su = max(0.0, min(1.0, float(param.get("u", 0.5))))
        sv = max(0.0, min(1.0, float(param.get("v", 0.5))))
        eps = 0.02
        origin = self._surface_point(face, su, sv)
        p_u = self._surface_point(face, min(1.0, su + eps), sv)
        p_v = self._surface_point(face, su, min(1.0, sv + eps))
        return self._stable_frame(origin, p_u, p_v)

    def _vertex_attachment_frame(self, param):
        origin = self.compute_local_point(param)
        if not self.points:
            return origin, Vector((1.0, 0.0, 0.0)), Vector((0.0, 0.0, 1.0))
        idx = self._safe_point_index(param)
        j = (idx + 1) % len(self.points)
        k = (idx + 2) % len(self.points)
        pj = self.apply_point_deformers(self.points[j].copy())
        pk = self.apply_point_deformers(self.points[k].copy())
        return self._stable_frame(origin, pj, pk)

    def _safe_point_index(self, param):
        try:
            idx = int(param)
        except Exception:
            idx = 0
        return max(0, min(len(self.points) - 1, idx))

    def _stable_frame(self, origin, p_u, p_v):
        tangent = p_u - origin
        if tangent.length <= 1e-8:
            tangent = Vector((1.0, 0.0, 0.0))
        else:
            tangent.normalize()
        normal = tangent.cross(p_v - origin)
        if normal.length <= 1e-8:
            normal = tangent.cross(Vector((0.0, 0.0, 1.0)))
        if normal.length <= 1e-8:
            normal = tangent.cross(Vector((0.0, 1.0, 0.0)))
        if normal.length <= 1e-8:
            normal = Vector((0.0, 0.0, 1.0))
        else:
            normal.normalize()
        return origin, tangent, normal

    def unbend_local_point(self, p):
        # Backward-compatible alias used by existing sync code.
        return self.invert_point_deformers(p)

    def bend_frame(self, axis):
        sx, sy, sz = self.size
        if axis == "Y":
            span = max(1e-8, float(sy))
        elif axis == "Z":
            span = max(1e-8, float(sz))
        else:
            span = max(1e-8, float(sx))
        return 0.0, span, 0.0

    def world_handle_to_base_point(self, proxy_obj, world_location):
        local_deformed = proxy_obj.matrix_world.inverted() @ world_location
        return self.invert_point_deformers(local_deformed)

    def _trilinear_point(self, u, v, w):
        p = self.points
        return (
            p[0] * ((1 - u) * (1 - v) * (1 - w))
            + p[1] * (u * (1 - v) * (1 - w))
            + p[2] * (u * v * (1 - w))
            + p[3] * ((1 - u) * v * (1 - w))
            + p[4] * ((1 - u) * (1 - v) * w)
            + p[5] * (u * (1 - v) * w)
            + p[6] * (u * v * w)
            + p[7] * ((1 - u) * v * w)
        )

    def _surface_mesh(self):
        n = self.resolution
        verts = []
        faces = []
        vmap = {}

        def add_lattice(iu, iv, iw):
            key = (iu, iv, iw)
            idx = vmap.get(key)
            if idx is not None:
                return idx

            u = iu / float(n)
            v = iv / float(n)
            w = iw / float(n)
            p = self._trilinear_point(u, v, w)
            p = self.apply_point_deformers(p)
            idx = len(verts)
            verts.append((p.x, p.y, p.z))
            vmap[key] = idx
            return idx

        self._append_x_faces(n, add_lattice, faces)
        self._append_y_faces(n, add_lattice, faces)
        self._append_z_faces(n, add_lattice, faces)

        return verts, faces

    def _append_x_faces(self, n, add_lattice, faces):
        for iv in range(n):
            for iw in range(n):
                faces.append((add_lattice(0, iv, iw), add_lattice(0, iv + 1, iw), add_lattice(0, iv + 1, iw + 1), add_lattice(0, iv, iw + 1)))
                faces.append((add_lattice(n, iv, iw), add_lattice(n, iv, iw + 1), add_lattice(n, iv + 1, iw + 1), add_lattice(n, iv + 1, iw)))

    def _append_y_faces(self, n, add_lattice, faces):
        for iu in range(n):
            for iw in range(n):
                faces.append((add_lattice(iu, 0, iw), add_lattice(iu + 1, 0, iw), add_lattice(iu + 1, 0, iw + 1), add_lattice(iu, 0, iw + 1)))
                faces.append((add_lattice(iu, n, iw), add_lattice(iu, n, iw + 1), add_lattice(iu + 1, n, iw + 1), add_lattice(iu + 1, n, iw)))

    def _append_z_faces(self, n, add_lattice, faces):
        for iu in range(n):
            for iv in range(n):
                faces.append((add_lattice(iu, iv, 0), add_lattice(iu, iv + 1, 0), add_lattice(iu + 1, iv + 1, 0), add_lattice(iu + 1, iv, 0)))
                faces.append((add_lattice(iu, iv, n), add_lattice(iu + 1, iv, n), add_lattice(iu + 1, iv + 1, n), add_lattice(iu, iv + 1, n)))

    def ensure_proxy_object(self, obj):
        if obj.type != "MESH":
            raise TypeError(f"Parallelepiped proxy must be MESH, got {obj.type}")

        if obj.data is None:
            obj.data = bpy.data.meshes.new(f"{obj.name}_mesh")

        mesh = obj.data
        verts, faces = self._surface_mesh()
        mesh.clear_geometry()
        mesh.from_pydata(verts, [], faces)
        mesh.update()

        obj.display_type = "SOLID"
        obj.hide_render = False


ShapeRegistry.register(ParallelepipedShape)
