import bpy


class AF_SCP_Property(bpy.types.PropertyGroup):

    id: bpy.props.StringProperty(name="ID")

    shape_type: bpy.props.StringProperty(name="Shape Type")

    # Transform
    local_origin: bpy.props.FloatVectorProperty(size=3)
    local_rotation: bpy.props.FloatVectorProperty(size=4)  # quaternion
    local_scale: bpy.props.FloatVectorProperty(size=3)

    # Attachment
    parent_id: bpy.props.StringProperty(name="Parent ID")
    attach_param: bpy.props.StringProperty(name="Attach Param JSON")

class AF_System_Property(bpy.types.PropertyGroup):
    scps: bpy.props.CollectionProperty(type=AF_SCP_Property)