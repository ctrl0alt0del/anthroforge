from mathutils import Vector
import bpy
from .base import ShapeStrategy
from .registry import ShapeRegistry

class CurveShape(ShapeStrategy):
    
    type_id = "CURVE"
    label = "Curve"

    proxy_object_type = "CURVE"
    proxy_data_type = "CURVE"

    def __init__(self, length=1.0, segments=5):
        self.length = length
        self.segments = segments

    @classmethod
    def from_scp_prop(cls, scp_prop):
        return cls(
            length=scp_prop.curve_length,
            segments=scp_prop.curve_segments,
        )

    @classmethod
    def init_scp_prop_defaults(cls, scp_prop):
        scp_prop.curve_length = 1.0
        scp_prop.curve_segments = 5

    def get_attach_params(self):
        # t ∈ [0, 1]
        return [i / self.segments for i in range(self.segments + 1)]

    def compute_local_point(self, t):
        # Curve aligned to local X axis
        return Vector((t * self.length, 0, 0))

    def ensure_proxy_object(self, obj):
        """
        Ensure proxy object is a CURVE datablock representing a straight line
        along local +X from 0 to self.length.
        """
        if obj.type != "CURVE":
            # Replace object data with a curve datablock
            curve_data = bpy.data.curves.new(f"{obj.name}_curve", type="CURVE")
            obj.data = curve_data

        curve_data = obj.data
        curve_data.dimensions = "3D"
        curve_data.resolution_u = 1
        curve_data.bevel_depth = 0.0
        curve_data.fill_mode = "NONE"

        # Clear existing splines
        while curve_data.splines:
            curve_data.splines.remove(curve_data.splines[0])

        spline = curve_data.splines.new(type="POLY")
        spline.points.add(1)  # total 2 points
        spline.points[0].co = (0.0, 0.0, 0.0, 1.0)
        spline.points[1].co = (self.length, 0.0, 0.0, 1.0)

        obj.display_type = "WIRE"
        obj.hide_render = True

    @classmethod
    def register_scene_props(cls):
        bpy.types.Scene.af_new_curve_length = bpy.props.FloatProperty(
            name="Length", default=1.0, min=0.001
        )
        bpy.types.Scene.af_new_curve_segments = bpy.props.IntProperty(
            name="Segments", default=5, min=1, max=256
        )

    @classmethod
    def unregister_scene_props(cls):
        if hasattr(bpy.types.Scene, "af_new_curve_length"):
            del bpy.types.Scene.af_new_curve_length
        if hasattr(bpy.types.Scene, "af_new_curve_segments"):
            del bpy.types.Scene.af_new_curve_segments

    @classmethod
    def apply_creation_to_scp(cls, scene, scp_prop):
        scp_prop.curve_length = scene.af_new_curve_length
        scp_prop.curve_segments = scene.af_new_curve_segments

    @classmethod
    def draw_creation_ui(cls, layout, scene):
        layout.prop(scene, "af_new_curve_length")
        layout.prop(scene, "af_new_curve_segments")

    @classmethod
    def draw_scp_ui(cls, layout, scp_prop, readonly=False):
        col = layout.column()
        col.enabled = not readonly
        col.prop(scp_prop, "curve_length")
        col.prop(scp_prop, "curve_segments")

ShapeRegistry.register(CurveShape)