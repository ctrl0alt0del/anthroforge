import bpy


class AF_DataShortcut_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="Shortcut")
    owner_type: bpy.props.StringProperty(name="Owner Type", default="NONE")
    owner_id: bpy.props.StringProperty(name="Owner ID", default="")
    data_path: bpy.props.StringProperty(name="Data Path", default="")


class AF_DataShortcut_System_Property(bpy.types.PropertyGroup):
    shortcuts: bpy.props.CollectionProperty(type=AF_DataShortcut_Property)
    active_shortcut_index: bpy.props.IntProperty(default=-1)
