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
from .operators.add_muscle_vcp import AF_OT_AddMuscleVCP
from .operators.delete_af_node import AF_OT_DeleteSelectedAFNode
from .operators.fiber_tools import (
    AF_OT_ClearFiberWarmStart,
    AF_OT_RecomputeFiber,
    AF_OT_AddFiberTouchPoint,
    AF_OT_RemoveFiberTouchPoint,
)
from .operators.muscle_tools import AF_OT_FlipMuscleNormals
from .operators.register_mesh_scp_asset import AF_OT_RegisterMeshSCPAsset
from .operators.mesh_asset_list import AF_OT_SelectMeshSCPAsset, AF_OT_DeleteMeshSCPAsset


from .ui.main_panel import AF_PT_MainPanel
from .ui.panels.create_panel import AF_PT_CreatePanel
from .ui.panels.tree_panel import AF_PT_TreePanel
from .ui.panels.edit_panel import AF_PT_EditPanel
from .ui.panels.fiber_edit_panel import AF_PT_FiberEditPanel
from .ui.panels.fiber_create_panel import AF_PT_FiberCreatePanel
from .ui.panels.vcp_edit_panel import AF_PT_VCPEditPanel

from .properties.scp_properties import AF_SCP_Property, AF_SCP_System_Property
from .properties.vcp_properties import (
    AF_MuscleFiberRef_Property,
    AF_MuscleVCP_Property,
    AF_FiberTouchPoint_Property,
    AF_FiberVCP_Property,
    AF_VCP_System_Property,
)

from .core.shapes import *  # registers shape classes
from .core.visualization.sync import register_sync, unregister_sync
from .core.visualization.fiber_sync import register_fiber_sync, unregister_fiber_sync
from .core.visualization.muscle_sync import register_muscle_sync, unregister_muscle_sync
from .ui.scene_props import register_scene_props, unregister_scene_props

addon_keymaps = []

classes = (
    AF_OT_CreateRoot,
    AF_OT_AddSCP,
    AF_OT_RegisterMeshSCPAsset,
    AF_OT_ToggleSCPCollapse,
    AF_OT_SelectSCPInTree,
    AF_OT_SelectMeshSCPAsset,
    AF_OT_DeleteMeshSCPAsset,
    AF_PT_MainPanel,
    AF_PT_CreatePanel,
    AF_PT_TreePanel,
    AF_PT_EditPanel,

    AF_SCP_Property,
    AF_SCP_System_Property,

    AF_OT_ClearFiberWarmStart,
    AF_OT_RecomputeFiber,
    AF_OT_AddFiberTouchPoint,
    AF_OT_RemoveFiberTouchPoint,

    AF_PT_FiberEditPanel,
    AF_PT_FiberCreatePanel,

    # Register nested property item type BEFORE owner types.
    AF_MuscleFiberRef_Property,
    AF_MuscleVCP_Property,
    AF_FiberTouchPoint_Property,
    AF_FiberVCP_Property,
    AF_VCP_System_Property,

    AF_OT_AddFiberVCP,
    AF_OT_AddMuscleVCP,
    AF_OT_ToggleVCPCollapse,
    AF_OT_SelectVCPInTree,

    AF_OT_DeleteSelectedAFNode,
    AF_PT_VCPEditPanel,
    AF_OT_FlipMuscleNormals,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Object.af_scp_system = bpy.props.PointerProperty(type=AF_SCP_System_Property)
    bpy.types.Object.af_vcp_system = bpy.props.PointerProperty(type=AF_VCP_System_Property)

    register_scene_props()
    register_sync()
    register_fiber_sync()
    register_muscle_sync()

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="Object Mode", space_type="EMPTY")
        kmi = km.keymap_items.new("af.delete_selected_af_node", "DEL", "PRESS")
        addon_keymaps.append((km, kmi))


def unregister():
    unregister_muscle_sync()
    unregister_fiber_sync()
    unregister_sync()
    unregister_scene_props()

    del bpy.types.Object.af_scp_system
    del bpy.types.Object.af_vcp_system

    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
