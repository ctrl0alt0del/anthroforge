import bpy


class AF_MuscleVCP_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="Muscle")


class AF_FiberVCP_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")

    # Endpoints (attachments to SCP)
    a_parent_id: bpy.props.StringProperty(name="Origin SCP ID")
    a_attach_param: bpy.props.StringProperty(name="Origin Attach Param JSON")
    b_parent_id: bpy.props.StringProperty(name="Insertion SCP ID")
    b_attach_param: bpy.props.StringProperty(name="Insertion Attach Param JSON")

    # Grouping
    muscle_id: bpy.props.StringProperty(name="Muscle ID", default="")

    # Solver state / settings
    rest_length: bpy.props.FloatProperty(name="Rest Length", default=0.0, min=0.0)
    node_count: bpy.props.IntProperty(name="Node Count", default=64, min=8, max=512)

    iterations_interactive: bpy.props.IntProperty(
        name="Iterations (Interactive)", default=12, min=1, max=200
    )
    iterations_bake: bpy.props.IntProperty(
        name="Iterations (Bake)", default=120, min=1, max=1000
    )

    stretch_enabled: bpy.props.BoolProperty(name="Stretch Enabled", default=True)
    max_stretch: bpy.props.FloatProperty(name="Max Stretch", default=1, min=1.0, max=10.0)
    stretch_stiffness: bpy.props.FloatProperty(name="Stretch Stiffness", default=0.6, min=0.0, max=1.0)

    bend_stiffness: bpy.props.FloatProperty(name="Bend Stiffness", default=0.25, min=0.0, max=1.0)
    collision_margin: bpy.props.FloatProperty(name="Collision Margin", default=0.002, min=0.0, max=1.0)
    damping: bpy.props.FloatProperty(name="Damping", default=0.15, min=0.0, max=1.0)

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
    use_warm_start: bpy.props.BoolProperty(
        name="Use Warm Start",
        default=True
    )



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
