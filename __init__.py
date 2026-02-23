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
from .operators.tree import (
    AF_OT_ToggleSCPCollapse,
    AF_OT_SelectSCPInTree,
    AF_OT_ToggleVCPCollapse,
    AF_OT_SelectVCPInTree,
)
from .operators.add_fiber_vcp import AF_OT_AddFiberVCP

from .ui.main_panel import AF_PT_MainPanel
from .ui.panels.create_panel import AF_PT_CreatePanel
from .ui.panels.tree_panel import AF_PT_TreePanel
from .ui.panels.edit_panel import AF_PT_EditPanel
from .ui.panels.vcp_tree_panel import AF_PT_VCPTreePanel

from .properties.scp_properties import AF_SCP_Property, AF_SCP_System_Property
from .core.shapes import *  # registers shape classes
from .core.visualization.sync import register_sync, unregister_sync
from .ui.scene_props import register_scene_props, unregister_scene_props
from .properties.vcp_properties import AF_FiberVCP_Property, AF_MuscleVCP_Property, AF_VCP_System_Property
from .ui.panels.fiber_create_panel import AF_PT_FiberCreatePanel



classes = (
    AF_OT_CreateRoot,
    AF_OT_AddSCP,
    AF_OT_ToggleSCPCollapse,
    AF_OT_SelectSCPInTree,
    AF_PT_MainPanel,
    AF_PT_CreatePanel,
    AF_PT_TreePanel,
    AF_PT_EditPanel,
    AF_SCP_Property,
    AF_SCP_System_Property,
    AF_PT_FiberCreatePanel,
    AF_MuscleVCP_Property,
    AF_FiberVCP_Property,
    AF_VCP_System_Property,
    AF_OT_AddFiberVCP,
    AF_OT_ToggleVCPCollapse,
    AF_OT_SelectVCPInTree,
    AF_PT_VCPTreePanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Object.af_scp_system = bpy.props.PointerProperty(type=AF_SCP_System_Property)
    bpy.types.Object.af_vcp_system = bpy.props.PointerProperty(type=AF_VCP_System_Property)
    register_scene_props()
    register_sync()


def unregister():
    unregister_sync()
    unregister_scene_props()
    del bpy.types.Object.af_scp_system
    del bpy.types.Object.af_vcp_system
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
