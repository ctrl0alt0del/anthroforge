import bpy


class AF_MuscleVCP_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="Muscle")


class AF_FiberVCP_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")

    # End A attachment (SCP + attach payload JSON)
    a_parent_id: bpy.props.StringProperty(name="A Parent SCP ID")
    a_attach_param: bpy.props.StringProperty(name="A Attach Param JSON")

    # End B attachment
    b_parent_id: bpy.props.StringProperty(name="B Parent SCP ID")
    b_attach_param: bpy.props.StringProperty(name="B Attach Param JSON")

    # Grouping
    muscle_id: bpy.props.StringProperty(name="Muscle ID", default="")

    # Authoring params
    resolution: bpy.props.IntProperty(name="Resolution", default=16, min=2, max=256)
    thickness: bpy.props.FloatProperty(name="Thickness", default=0.01, min=0.0)


class AF_VCP_System_Property(bpy.types.PropertyGroup):
    muscles: bpy.props.CollectionProperty(type=AF_MuscleVCP_Property)
    fibers: bpy.props.CollectionProperty(type=AF_FiberVCP_Property)

    # Current active node in VCP tree
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

    # Keep old field for compatibility if used elsewhere
    active_fiber_index: bpy.props.IntProperty(default=-1)
