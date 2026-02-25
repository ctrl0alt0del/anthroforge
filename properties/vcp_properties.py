import bpy
from ..core.utils import get_af_root


def _sync_muscle_scene(context):
    if context is None:
        return
    scene = context.scene
    root = get_af_root(scene)
    if root is None:
        return
    from ..core.visualization.muscle_sync import register_muscle_sync
    register_muscle_sync().sync_root_to_scene(root=root, scene=scene)


def _on_muscle_prop_update(self, context):
    _sync_muscle_scene(context)


class AF_MuscleFiberRef_Property(bpy.types.PropertyGroup):
    fiber_id: bpy.props.StringProperty(name="Fiber ID", default="")


class AF_MuscleVCP_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="Muscle", update=_on_muscle_prop_update)

    # Stitching behavior (v1)
    closed_v: bpy.props.BoolProperty(name="Closed Ring (V)", default=False, update=_on_muscle_prop_update)

    # Ordered fibers (manual order)
    fiber_refs: bpy.props.CollectionProperty(type=AF_MuscleFiberRef_Property)
    active_fiber_ref_index: bpy.props.IntProperty(name="Active Fiber Ref", default=-1)

    # Inflation control (gizmo-driven max point)
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

    # Cached world-space control position (written by muscle inflation gizmo sync)
    inflation_ctrl_world: bpy.props.FloatVectorProperty(
        name="Inflation Ctrl World",
        size=3,
        subtype="TRANSLATION",
        default=(0.0, 0.0, 0.0),
    )

    flip_normals: bpy.props.BoolProperty(
        name="Flip Normals",
        default=False,
        update=_on_muscle_prop_update,  # if you already use this callback
    )



class AF_FiberTouchPoint_Property(bpy.types.PropertyGroup):
    parent_id: bpy.props.StringProperty(name="Touch SCP ID", default="")
    attach_param: bpy.props.StringProperty(name="Touch Attach Param JSON", default="0.0")


class AF_FiberVCP_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="")

    # Endpoints (attachments to SCP)
    a_parent_id: bpy.props.StringProperty(name="Origin SCP ID")
    a_attach_param: bpy.props.StringProperty(name="Origin Attach Param JSON")
    b_parent_id: bpy.props.StringProperty(name="Insertion SCP ID")
    b_attach_param: bpy.props.StringProperty(name="Insertion Attach Param JSON")

    # Mid touch points (ordered)
    mid_touches: bpy.props.CollectionProperty(type=AF_FiberTouchPoint_Property)
    guide_stiffness: bpy.props.FloatProperty(name="Guide Stiffness", default=1.0, min=0.0, max=1.0)

    # Grouping
    muscle_id: bpy.props.StringProperty(name="Muscle ID", default="")

    # Solver settings/state
    node_count: bpy.props.IntProperty(name="Node Count", default=64, min=8, max=512)
    iterations_interactive: bpy.props.IntProperty(name="Iterations (Interactive)", default=12, min=1, max=200)
    iterations_bake: bpy.props.IntProperty(name="Iterations (Bake)", default=120, min=1, max=1000)

    bend_stiffness: bpy.props.FloatProperty(name="Bend Stiffness", default=0.15, min=0.0, max=1.0)
    collision_margin: bpy.props.FloatProperty(name="Collision Margin", default=0.002, min=0.0, max=1.0)
    damping: bpy.props.FloatProperty(name="Damping", default=0.10, min=0.0, max=1.0)

    # Kept for current solver shortening pass
    stretch_stiffness: bpy.props.FloatProperty(name="Shorten Strength", default=0.9, min=0.0, max=1.0)

    # Visualization / status
    thickness: bpy.props.FloatProperty(name="Thickness", default=0.01, min=0.0)
    not_converged: bpy.props.BoolProperty(name="Not Converged", default=False)
    last_recompute_ms: bpy.props.FloatProperty(name="Last Recompute (ms)", default=0.0)
    last_recompute_status: bpy.props.EnumProperty(
        name="Last Recompute Status",
        items=(
            ("UNKNOWN", "Unknown", ""),
            ("CONVERGED", "Converged", ""),
            ("NOT_CONVERGED", "Not Converged", ""),
        ),
        default="UNKNOWN",
    )
    last_eps_disp: bpy.props.FloatProperty(name="Last Disp Eps", default=0.0)
    last_eps_pen: bpy.props.FloatProperty(name="Last Pen Eps", default=0.0)


class AF_VCP_System_Property(bpy.types.PropertyGroup):
    muscles: bpy.props.CollectionProperty(type=AF_MuscleVCP_Property)
    fibers: bpy.props.CollectionProperty(type=AF_FiberVCP_Property)

    active_vcp_id: bpy.props.StringProperty(name="Active VCP ID", default="")
    active_vcp_type: bpy.props.EnumProperty(
        name="Active VCP Type",
        items=(
            ("NONE", "None", ""),
            ("MUSCLE", "Muscle", ""),
            ("FIBER", "Fiber", ""),
        ),
        default="NONE",
    )

    active_fiber_index: bpy.props.IntProperty(default=-1)
    active_muscle_index: bpy.props.IntProperty(default=-1)
