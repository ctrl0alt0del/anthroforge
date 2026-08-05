import bpy

from ..core.topology.constants import DEFAULT_TARGET_QUADS, MAX_TARGET_QUADS, MIN_TARGET_QUADS


class AF_TopologySettings_Property(bpy.types.PropertyGroup):
    target_quad_count: bpy.props.IntProperty(
        name="Target Quads", description="Approximate final all-quad face count",
        default=DEFAULT_TARGET_QUADS, min=MIN_TARGET_QUADS, max=MAX_TARGET_QUADS,
    )
    refinement_strategy: bpy.props.EnumProperty(
        name="Deformation Refinement", default="NONE",
        items=(("NONE", "None", "Use geometry and authored density only"),
               ("MUSCLE_PROXIMITY", "Muscle Proximity",
                "Reserve additional topology near final muscle surfaces")),
    )
    symmetry_mode: bpy.props.EnumProperty(
        name="Symmetry", default="X",
        items=(("NONE", "None", "Generate without enforced symmetry"),
               ("X", "Root X", "Root-local X symmetry plane"),
               ("Y", "Root Y", "Root-local Y symmetry plane"),
               ("Z", "Root Z", "Root-local Z symmetry plane"),
               ("CUSTOM", "Custom", "Custom root-local origin and normal")),
    )
    custom_origin: bpy.props.FloatVectorProperty(
        name="Plane Origin", size=3, default=(0.0, 0.0, 0.0), subtype="XYZ")
    custom_normal: bpy.props.FloatVectorProperty(
        name="Plane Normal", size=3, default=(1.0, 0.0, 0.0), subtype="DIRECTION")
