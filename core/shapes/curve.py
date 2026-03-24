from mathutils import Vector
import bpy
from .base import ShapeStrategy
from .deformers import MirrorDeformer, ResolutionDeformer
from .registry import ShapeRegistry


class CurveShape(ShapeStrategy):
    type_id = "CURVE"
    label = "Curve"

    proxy_object_type = "CURVE"
    proxy_data_type = "CURVE"
    supports_fiber_collision = False
    _MIRROR = MirrorDeformer()
    _RESOLUTION = ResolutionDeformer()

    def __init__(self, length=1.0, segments=5, thickness=0.02, points=None):
        self.length = float(length)
        self.segments = max(1, int(segments))
        self.thickness = max(0.0, float(thickness))
        self.points = points or self._build_linear_points(self.length, self.segments)

    @staticmethod
    def _build_linear_points(length, segments):
        out = []
        segments = max(1, int(segments))
        length = float(length)
        for i in range(segments + 1):
            t = i / float(segments)
            out.append(Vector((t * length, 0.0, 0.0)))
        return out

    @staticmethod
    def _points_from_prop(scp_prop):
        pts = [Vector((p.co[0], p.co[1], p.co[2])) for p in scp_prop.curve_points]
        expected = max(1, int(scp_prop.curve_segments)) + 1
        if len(pts) != expected:
            return CurveShape._build_linear_points(scp_prop.curve_length, scp_prop.curve_segments)
        return pts

    @classmethod
    def from_scp_prop(cls, scp_prop):
        return cls(
            length=scp_prop.curve_length,
            segments=scp_prop.curve_segments,
            thickness=scp_prop.curve_thickness,
            points=cls._points_from_prop(scp_prop),
        )

    @classmethod
    def init_scp_prop_defaults(cls, scp_prop):
        scp_prop.curve_length = 1.0
        scp_prop.curve_segments = 5
        scp_prop.curve_thickness = 0.02
        scp_prop.curve_proportional_enabled = True
        scp_prop.curve_proportional_radius = 2.0
        scp_prop.curve_proportional_strength = 0.65

        while len(scp_prop.curve_points) > 0:
            scp_prop.curve_points.remove(len(scp_prop.curve_points) - 1)
        for p in cls._build_linear_points(scp_prop.curve_length, scp_prop.curve_segments):
            cp = scp_prop.curve_points.add()
            cp.co = (p.x, p.y, p.z)

    def get_attach_params(self):
        return [i / self.segments for i in range(self.segments + 1)]

    def get_deformers(self):
        return [self._MIRROR, self._RESOLUTION]

    def compute_local_point(self, t):
        if not self.points:
            return Vector((0.0, 0.0, 0.0))
        if len(self.points) == 1:
            return self.points[0].copy()

        t = max(0.0, min(1.0, float(t)))
        u = t * self.segments
        i = int(u)
        if i >= self.segments:
            return self.points[-1].copy()

        a = u - i
        return self.apply_point_deformers(self.points[i].lerp(self.points[i + 1], a))

    def ensure_proxy_object(self, obj):
        if obj.type != "CURVE":
            curve_data = bpy.data.curves.new(f"{obj.name}_curve", type="CURVE")
            obj.data = curve_data

        curve_data = obj.data
        curve_data.dimensions = "3D"
        curve_data.resolution_u = 8
        curve_data.bevel_depth = self.thickness
        curve_data.bevel_resolution = 2
        curve_data.fill_mode = "FULL"

        while curve_data.splines:
            curve_data.splines.remove(curve_data.splines[0])

        spline = curve_data.splines.new(type="POLY")
        spline.points.add(max(0, len(self.points) - 1))

        for i, p in enumerate(self.points):
            q = self.apply_point_deformers(p.copy())
            spline.points[i].co = (q.x, q.y, q.z, 1.0)

        obj.display_type = "TEXTURED"
        obj.hide_render = False

    @classmethod
    def register_scene_props(cls):
        bpy.types.Scene.af_new_curve_length = bpy.props.FloatProperty(
            name="Length", default=1.0, min=0.001
        )
        bpy.types.Scene.af_new_curve_segments = bpy.props.IntProperty(
            name="Segments", default=5, min=1, max=256
        )
        bpy.types.Scene.af_new_curve_thickness = bpy.props.FloatProperty(
            name="Thickness", default=0.02, min=0.0
        )

    @classmethod
    def unregister_scene_props(cls):
        if hasattr(bpy.types.Scene, "af_new_curve_length"):
            del bpy.types.Scene.af_new_curve_length
        if hasattr(bpy.types.Scene, "af_new_curve_segments"):
            del bpy.types.Scene.af_new_curve_segments
        if hasattr(bpy.types.Scene, "af_new_curve_thickness"):
            del bpy.types.Scene.af_new_curve_thickness

    @classmethod
    def apply_creation_to_scp(cls, scene, scp_prop):
        scp_prop.curve_length = scene.af_new_curve_length
        scp_prop.curve_segments = scene.af_new_curve_segments
        scp_prop.curve_thickness = scene.af_new_curve_thickness
        scp_prop.curve_proportional_enabled = True
        scp_prop.curve_proportional_radius = 2.0
        scp_prop.curve_proportional_strength = 0.65

        while len(scp_prop.curve_points) > 0:
            scp_prop.curve_points.remove(len(scp_prop.curve_points) - 1)
        for p in cls._build_linear_points(scp_prop.curve_length, scp_prop.curve_segments):
            cp = scp_prop.curve_points.add()
            cp.co = (p.x, p.y, p.z)

    @classmethod
    def draw_creation_ui(cls, layout, scene):
        layout.prop(scene, "af_new_curve_length")
        layout.prop(scene, "af_new_curve_segments")
        layout.prop(scene, "af_new_curve_thickness")

    @classmethod
    def draw_scp_ui(cls, layout, scp_prop, readonly=False):
        col = layout.column()
        col.enabled = not readonly
        col.prop(scp_prop, "curve_length")
        col.prop(scp_prop, "curve_segments")
        col.prop(scp_prop, "curve_thickness")
        col.prop(scp_prop, "curve_proportional_enabled")
        pcol = col.column()
        pcol.enabled = bool(scp_prop.curve_proportional_enabled)
        pcol.prop(scp_prop, "curve_proportional_radius")
        pcol.prop(scp_prop, "curve_proportional_strength")

        box = col.box()
        box.label(text="Curve Points")
        for i, p in enumerate(scp_prop.curve_points):
            row = box.row(align=True)
            row.label(text=f"P{i}")
            row.prop(p, "co", text="")


ShapeRegistry.register(CurveShape)
