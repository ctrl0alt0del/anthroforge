import bpy
from math import atan2, cos, radians, sin, sqrt
from mathutils import Vector

from .base import ShapeStrategy
from .registry import ShapeRegistry


class ParallelepipedShape(ShapeStrategy):
    type_id = "PARALLELEPIPED"
    label = "Parallelepiped"

    proxy_object_type = "MESH"
    proxy_data_type = "MESH"
    supports_fiber_collision = True

    FACES = [
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]

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

    def get_attach_params(self):
        return list(range(len(self.points)))

    def compute_local_point(self, param):
        try:
            idx = int(param)
        except Exception:
            idx = 0
        if not self.points:
            return Vector((0.0, 0.0, 0.0))
        idx = max(0, min(len(self.points) - 1, idx))
        return self._bend_point(self.points[idx].copy())

    def _bend_point(self, p):
        if not self.bend_enabled:
            return p

        angle_rad = radians(self.bend_angle_deg)
        if abs(angle_rad) <= 1e-9:
            return p

        axis = self.bend_axis
        u_center, span, v_center = self._bend_frame(axis)
        if axis == "Y":
            u = p.y
            v = p.z
            w = p.x
        elif axis == "Z":
            u = p.z
            v = p.x
            w = p.y
        else:
            u = p.x
            v = p.y
            w = p.z
        theta = ((u - u_center) / span) * angle_rad

        r0 = max(1e-6, self.bend_radius)
        v_local = v - v_center
        r = max(1e-6, r0 + v_local)
        new_u = u_center + (sin(theta) * r)
        new_v = v_center + ((cos(theta) * r) - r0)

        if axis == "Y":
            return Vector((w, new_u, new_v))
        if axis == "Z":
            return Vector((new_v, w, new_u))
        return Vector((new_u, new_v, w))

    def unbend_local_point(self, p):
        if not self.bend_enabled:
            return p.copy()

        angle_rad = radians(self.bend_angle_deg)
        if abs(angle_rad) <= 1e-9:
            return p.copy()

        axis = self.bend_axis
        u_center, span, v_center = self._bend_frame(axis)
        if axis == "Y":
            new_u = p.y
            new_v = p.z
            w = p.x
        elif axis == "Z":
            new_u = p.z
            new_v = p.x
            w = p.y
        else:
            new_u = p.x
            new_v = p.y
            w = p.z
        r0 = max(1e-6, self.bend_radius)

        su = new_u - u_center
        cv = (new_v - v_center) + r0
        r = max(1e-6, sqrt((su * su) + (cv * cv)))
        theta = atan2(su, cv)

        u = u_center + (theta / angle_rad) * span
        v_local = r - r0
        v = v_center + v_local

        if axis == "Y":
            return Vector((w, u, v))
        if axis == "Z":
            return Vector((v, w, u))
        return Vector((u, v, w))

    def _bend_frame(self, axis):
        sx, sy, sz = self.size
        if axis == "Y":
            span = max(1e-8, float(sy))
        elif axis == "Z":
            span = max(1e-8, float(sz))
        else:
            span = max(1e-8, float(sx))
        return 0.0, span, 0.0

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
            p = self._bend_point(p)
            idx = len(verts)
            verts.append((p.x, p.y, p.z))
            vmap[key] = idx
            return idx

        for iv in range(n):
            for iw in range(n):
                a = add_lattice(0, iv, iw)
                b = add_lattice(0, iv + 1, iw)
                c = add_lattice(0, iv + 1, iw + 1)
                d = add_lattice(0, iv, iw + 1)
                faces.append((a, b, c, d))

                a = add_lattice(n, iv, iw)
                b = add_lattice(n, iv, iw + 1)
                c = add_lattice(n, iv + 1, iw + 1)
                d = add_lattice(n, iv + 1, iw)
                faces.append((a, b, c, d))

        for iu in range(n):
            for iw in range(n):
                a = add_lattice(iu, 0, iw)
                b = add_lattice(iu + 1, 0, iw)
                c = add_lattice(iu + 1, 0, iw + 1)
                d = add_lattice(iu, 0, iw + 1)
                faces.append((a, b, c, d))

                a = add_lattice(iu, n, iw)
                b = add_lattice(iu, n, iw + 1)
                c = add_lattice(iu + 1, n, iw + 1)
                d = add_lattice(iu + 1, n, iw)
                faces.append((a, b, c, d))

        for iu in range(n):
            for iv in range(n):
                a = add_lattice(iu, iv, 0)
                b = add_lattice(iu, iv + 1, 0)
                c = add_lattice(iu + 1, iv + 1, 0)
                d = add_lattice(iu + 1, iv, 0)
                faces.append((a, b, c, d))

                a = add_lattice(iu, iv, n)
                b = add_lattice(iu + 1, iv, n)
                c = add_lattice(iu + 1, iv + 1, n)
                d = add_lattice(iu, iv + 1, n)
                faces.append((a, b, c, d))

        return verts, faces

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
