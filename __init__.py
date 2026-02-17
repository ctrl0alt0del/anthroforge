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
from .ui.main_panel import AF_PT_MainPanel
from .properties.scp_properties import AF_SCP_Property, AF_System_Property

classes = (
    AF_OT_CreateRoot,
    AF_PT_MainPanel,
    AF_SCP_Property,
    AF_System_Property,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.af_system = bpy.props.PointerProperty(
        type=AF_System_Property
    )

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
