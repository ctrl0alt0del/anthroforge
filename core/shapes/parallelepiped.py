import bpy
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

    def __init__(self, size=(1.0, 1.0, 1.0), points=None):
        self.size = tuple(float(v) for v in size)
        self.points = points or self._default_points(self.size)

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
        )

    @classmethod
    def init_scp_prop_defaults(cls, scp_prop):
        scp_prop.parallelepiped_size = (1.0, 1.0, 1.0)
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

    @classmethod
    def unregister_scene_props(cls):
        if hasattr(bpy.types.Scene, "af_new_parallelepiped_size"):
            del bpy.types.Scene.af_new_parallelepiped_size

    @classmethod
    def draw_creation_ui(cls, layout, scene):
        layout.prop(scene, "af_new_parallelepiped_size")

    @classmethod
    def apply_creation_to_scp(cls, scene, scp_prop):
        scp_prop.parallelepiped_size = scene.af_new_parallelepiped_size
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
        return self.points[idx].copy()

    def ensure_proxy_object(self, obj):
        if obj.type != "MESH":
            raise TypeError(f"Parallelepiped proxy must be MESH, got {obj.type}")

        if obj.data is None:
            obj.data = bpy.data.meshes.new(f"{obj.name}_mesh")

        mesh = obj.data
        verts = [(p.x, p.y, p.z) for p in self.points]
        mesh.clear_geometry()
        mesh.from_pydata(verts, [], self.FACES)
        mesh.update()

        obj.display_type = "SOLID"
        obj.hide_render = False


ShapeRegistry.register(ParallelepipedShape)
