bl_info = {
  "name": "AnthroForge",
  "author": "AnthroForge Team",
  "version": (0, 1, 0),
  "blender": (4, 4, 0),
  "location": "View3D > Sidebar > AnthroForge",
  "description": "Procedural anatomical construction system",
  "category": "Object",
}

import bpy

from .operators.create_root import AF_OT_CreateRoot
from .operators.add_scp import AF_OT_AddSCP
from .ui.main_panel import AF_PT_MainPanel
from .ui.scp_list import AF_UL_SCPList
from .properties.scp_properties import AF_SCP_Property, AF_System_Property
from .core.shapes.registry import ShapeRegistry
from .core.shapes import *
from .core.visualization.sync import register_sync, unregister_sync

classes = (
    AF_OT_CreateRoot,
    AF_OT_AddSCP,
    AF_UL_SCPList,
    AF_PT_MainPanel,
    AF_SCP_Property,
    AF_System_Property,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Object.af_system = bpy.props.PointerProperty(type=AF_System_Property)
    bpy.types.Scene.af_scp_type = bpy.props.EnumProperty(
        name="SCP Type",
        items=lambda self, context: ShapeRegistry.enum_items()
    )

    ShapeRegistry.register_scene_props()
    register_sync()

def unregister():
    unregister_sync()
    ShapeRegistry.unregister_scene_props()

    del bpy.types.Object.af_system
    del bpy.types.Scene.af_scp_type

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
