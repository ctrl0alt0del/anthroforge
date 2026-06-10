import bpy

from ..app.runtime_api import sync_context
from ..core.deps.dirty_hints import dirty_hints_for, empty_dirty_hints


def _sync_vcp_scene(context):
    sync_context(context, dirty_hints=empty_dirty_hints())


def _on_muscle_prop_update(self, context):
    sync_context(context, dirty_hints=dirty_hints_for("MUSCLE", {self.id}))


def _on_blob_prop_update(self, context):
    sync_context(context, dirty_hints=dirty_hints_for("BLOB", {self.id}))


class AF_MuscleFiberRef_Property(bpy.types.PropertyGroup):
    fiber_id: bpy.props.StringProperty(name="Fiber ID", default="")


class AF_MuscleVCP_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="Muscle", update=_on_muscle_prop_update)

    closed_v: bpy.props.BoolProperty(name="Closed Ring (V)", default=False, update=_on_muscle_prop_update)

    fiber_refs: bpy.props.CollectionProperty(type=AF_MuscleFiberRef_Property)
    active_fiber_ref_index: bpy.props.IntProperty(name="Active Fiber Ref", default=-1)

    inflation_enabled: bpy.props.BoolProperty(name="Inflation Enabled", default=True, update=_on_muscle_prop_update)
    inflation_max_value: bpy.props.FloatProperty(
        name="Max Inflation",
        default=0.05,
        min=0.0,
        max=10.0,
        update=_on_muscle_prop_update,
    )
    inflation_falloff_type: bpy.props.EnumProperty(
        name="Falloff",
        items=(
            ("GAUSSIAN", "Gaussian", ""),
            ("LINEAR", "Linear", ""),
            ("SMOOTHSTEP", "Smoothstep", ""),
        ),
        default="GAUSSIAN",
        update=_on_muscle_prop_update,
    )
    inflation_falloff_radius: bpy.props.FloatProperty(
        name="Falloff Radius",
        default=0.2,
        min=0.001,
        max=100.0,
        update=_on_muscle_prop_update,
    )

    inflation_direction_depth: bpy.props.FloatProperty(
        name="Direction Depth (L)",
        default=0.05,
        min=0.0001,
        max=10.0,
        update=_on_muscle_prop_update,
    )

    inflation_boundary_strength: bpy.props.FloatProperty(
        name="Boundary Strength",
        default=0.7, min=0.0, max=1.0, update=_on_muscle_prop_update
    )

    inflation_boundary_band: bpy.props.FloatProperty(
        name="Boundary Band",
        default=2.0, min=0.1, max=16.0, update=_on_muscle_prop_update
    )

    inflation_boundary_power: bpy.props.FloatProperty(
        name="Boundary Power",
        default=1.5, min=0.1, max=8.0, update=_on_muscle_prop_update
    )

    flip_normals: bpy.props.BoolProperty(
        name="Flip Normals",
        default=False,
        update=_on_muscle_prop_update,
    )


class AF_FiberTouchPoint_Property(bpy.types.PropertyGroup):
    parent_id: bpy.props.StringProperty(name="Touch SCP ID", default="")
    attach_param: bpy.props.StringProperty(name="Touch Attach Param JSON", default="0.0")


class AF_FiberVCP_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="")

    a_parent_id: bpy.props.StringProperty(name="Origin SCP ID")
    a_attach_param: bpy.props.StringProperty(name="Origin Attach Param JSON")
    b_parent_id: bpy.props.StringProperty(name="Insertion SCP ID")
    b_attach_param: bpy.props.StringProperty(name="Insertion Attach Param JSON")

    mid_touches: bpy.props.CollectionProperty(type=AF_FiberTouchPoint_Property)
    guide_stiffness: bpy.props.FloatProperty(name="Guide Stiffness", default=1.0, min=0.0, max=1.0)

    muscle_id: bpy.props.StringProperty(name="Muscle ID", default="")

    node_count: bpy.props.IntProperty(name="Node Count", default=64, min=8, max=512)
    iterations_interactive: bpy.props.IntProperty(name="Iterations (Interactive)", default=12, min=1, max=200)
    iterations_bake: bpy.props.IntProperty(name="Iterations (Bake)", default=120, min=1, max=1000)

    bend_stiffness: bpy.props.FloatProperty(name="Bend Stiffness", default=0.15, min=0.0, max=1.0)
    collision_margin: bpy.props.FloatProperty(name="Collision Margin", default=0.002, min=0.0, max=1.0)
    damping: bpy.props.FloatProperty(name="Damping", default=0.10, min=0.0, max=1.0)

    stretch_stiffness: bpy.props.FloatProperty(name="Shorten Strength", default=0.9, min=0.0, max=1.0)

    thickness: bpy.props.FloatProperty(name="Thickness", default=0.01, min=0.0)


class AF_BlobVCP_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="Blob", update=_on_blob_prop_update)

    center_world: bpy.props.FloatVectorProperty(
        name="Center", size=3, subtype="TRANSLATION", default=(0.0, 0.0, 0.0), update=_on_blob_prop_update
    )
    radius: bpy.props.FloatProperty(name="Radius", default=0.2, min=0.001, update=_on_blob_prop_update)
    shape: bpy.props.EnumProperty(
        name="Shape",
        items=(("SPHERE", "Sphere", ""), ("ELLIPSOID", "Ellipsoid", "")),
        default="SPHERE",
        update=_on_blob_prop_update,
    )
    axis_scale: bpy.props.FloatVectorProperty(
        name="Axis Scale", size=3, subtype="XYZ", default=(1.0, 1.0, 1.0), min=0.001, update=_on_blob_prop_update
    )
    resolution: bpy.props.IntProperty(name="Control Points", default=24, min=8, max=128, update=_on_blob_prop_update)

    # Explicit point used by solver ray tests.
    control_point_world: bpy.props.FloatVectorProperty(
        name="Control Point",
        size=3,
        subtype="TRANSLATION",
        default=(0.0, 0.0, 0.0),
        update=_on_blob_prop_update,
    )

    gravity_dir: bpy.props.FloatVectorProperty(
        name="Gravity Dir", size=3, subtype="XYZ", default=(0.0, 0.0, -1.0), update=_on_blob_prop_update
    )
    sag_strength: bpy.props.FloatProperty(name="Sag Strength", default=0.35, min=0.0, max=10.0, update=_on_blob_prop_update)
    sag_limit: bpy.props.FloatProperty(name="Sag Limit", default=0.35, min=0.0, max=100.0, update=_on_blob_prop_update)

    attach_target_type: bpy.props.EnumProperty(
        name="Target Type",
        items=(("NONE", "None", ""), ("MUSCLE", "Muscle", ""), ("SCP", "SCP", ""), ("OBJECT", "Object", "")),
        default="NONE",
        update=_on_blob_prop_update,
    )
    attach_target_id: bpy.props.StringProperty(name="Target ID", default="", update=_on_blob_prop_update)
    attach_target_object_name: bpy.props.StringProperty(name="Target Object", default="", update=_on_blob_prop_update)

    stiffness: bpy.props.FloatProperty(name="Stiffness", default=0.25, min=0.0, max=1.0, update=_on_blob_prop_update)
    iterations: bpy.props.IntProperty(name="Iterations", default=20, min=1, max=200, update=_on_blob_prop_update)


class AF_VCP_System_Property(bpy.types.PropertyGroup):
    muscles: bpy.props.CollectionProperty(type=AF_MuscleVCP_Property)
    fibers: bpy.props.CollectionProperty(type=AF_FiberVCP_Property)
    blobs: bpy.props.CollectionProperty(type=AF_BlobVCP_Property)

    active_vcp_id: bpy.props.StringProperty(name="Active VCP ID", default="")
    active_vcp_type: bpy.props.EnumProperty(
        name="Active VCP Type",
        items=(
            ("NONE", "None", ""),
            ("MUSCLE", "Muscle", ""),
            ("FIBER", "Fiber", ""),
            ("BLOB", "Blob", ""),
        ),
        default="NONE",
    )

