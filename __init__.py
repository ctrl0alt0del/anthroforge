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
from .operators.add_scp import AF_OT_AddSCP, AF_OT_SetSCPParent, AF_OT_UnmarkSCP
from .operators.tree import (
    AF_OT_ToggleSCPCollapse,
    AF_OT_SelectSCPInTree,
    AF_OT_ToggleVCPCollapse,
    AF_OT_SelectVCPInTree,
)
from .operators.add_fiber_vcp import AF_OT_AddFiberVCP
from .operators.add_muscle_vcp import AF_OT_AddMuscleVCP
from .operators.add_blob_vcp import AF_OT_AddBlobVCP
from .operators.fiber_tools import (
    AF_OT_ClearFiberWarmStart,
    AF_OT_RecomputeFiber,
    AF_OT_AddFiberTouchPoint,
    AF_OT_RemoveFiberTouchPoint,
)
from .operators.muscle_tools import (
    AF_OT_FlipMuscleNormals,
    AF_OT_SelectMuscleInflationCtrl,
)
from .operators.blob_tools import AF_OT_SelectBlobControl
from .operators.shortcuts import AF_OT_AddDataShortcut, AF_OT_DeleteDataShortcut
from .operators.scp_objects import (
    AF_OT_AddSCPBoundObject,
    AF_OT_CreateEmptySCP,
    AF_OT_RemoveSCPBoundObject,
    AF_OT_SetSCPGeometryObject,
    AF_OT_SetSCPTransformObject,
)

from .ui.main_panel import AF_PT_MainPanel
from .ui.panels.create_panel import AF_PT_CreatePanel
from .ui.panels.tree_panel import AF_PT_TreePanel
from .ui.panels.edit_panel import AF_PT_EditPanel
from .ui.panels.fiber_edit_panel import AF_PT_FiberEditPanel
from .ui.panels.fiber_create_panel import AF_PT_FiberCreatePanel
from .ui.panels.vcp_edit_panel import AF_PT_VCPEditPanel
from .ui.panels.blob_create_panel import AF_PT_BlobCreatePanel
from .ui.panels.blob_edit_panel import AF_PT_BlobEditPanel
from .ui.panels.scp_objects_panel import AF_PT_SCPObjectsPanel
from .ui.panels.shortcut_panel import AF_PT_ShortcutPanel

from .properties.scp_properties import (
    AF_SCP_BoundObject_Property,
    AF_SCP_Property,
    AF_SCP_System_Property,
)
from .properties.vcp_properties import (
    AF_MuscleFiberRef_Property,
    AF_MuscleVCP_Property,
    AF_FiberTouchPoint_Property,
    AF_FiberVCP_Property,
    AF_BlobVCP_Property,
    AF_VCP_System_Property,
)
from .properties.shortcut_properties import (
    AF_DataShortcut_Property,
    AF_DataShortcut_System_Property,
)

from .core.visualization.sync import register_sync, unregister_sync
from .core.visualization.fiber_sync import register_fiber_sync, unregister_fiber_sync
from .core.visualization.muscle_sync import register_muscle_sync, unregister_muscle_sync
from .core.visualization.blob_sync import register_blob_sync, unregister_blob_sync
from .core.visualization.control_runtime import (
    register_control_runtime,
    unregister_control_runtime,
)
from .core.visualization.delete_reconcile import (
    register_delete_reconcile,
    unregister_delete_reconcile,
)
from .ui.scene_props import register_scene_props, unregister_scene_props

classes = (
    AF_OT_CreateRoot,
    AF_OT_AddSCP,
    AF_OT_SetSCPParent,
    AF_OT_UnmarkSCP,
    AF_OT_CreateEmptySCP,
    AF_OT_SetSCPTransformObject,
    AF_OT_SetSCPGeometryObject,
    AF_OT_AddSCPBoundObject,
    AF_OT_RemoveSCPBoundObject,
    AF_OT_ToggleSCPCollapse,
    AF_OT_SelectSCPInTree,
    AF_PT_MainPanel,
    AF_PT_CreatePanel,
    AF_PT_SCPObjectsPanel,
    AF_PT_TreePanel,
    AF_PT_EditPanel,

    AF_SCP_BoundObject_Property,
    AF_SCP_Property,
    AF_SCP_System_Property,

    AF_OT_ClearFiberWarmStart,
    AF_OT_RecomputeFiber,
    AF_OT_AddFiberTouchPoint,
    AF_OT_RemoveFiberTouchPoint,

    AF_PT_FiberEditPanel,
    AF_PT_FiberCreatePanel,

    AF_MuscleFiberRef_Property,
    AF_MuscleVCP_Property,
    AF_FiberTouchPoint_Property,
    AF_FiberVCP_Property,
    AF_BlobVCP_Property,
    AF_VCP_System_Property,

    AF_OT_AddFiberVCP,
    AF_OT_AddMuscleVCP,
    AF_OT_AddBlobVCP,
    AF_OT_ToggleVCPCollapse,
    AF_OT_SelectVCPInTree,
    AF_PT_VCPEditPanel,
    AF_OT_FlipMuscleNormals,
    AF_OT_SelectMuscleInflationCtrl,
    AF_OT_SelectBlobControl,
    AF_PT_BlobCreatePanel,
    AF_PT_BlobEditPanel,
    AF_DataShortcut_Property,
    AF_DataShortcut_System_Property,
    AF_OT_AddDataShortcut,
    AF_OT_DeleteDataShortcut,
    AF_PT_ShortcutPanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Object.af_scp_system = bpy.props.PointerProperty(type=AF_SCP_System_Property)
    bpy.types.Object.af_vcp_system = bpy.props.PointerProperty(type=AF_VCP_System_Property)
    bpy.types.Object.af_shortcut_system = bpy.props.PointerProperty(type=AF_DataShortcut_System_Property)

    register_scene_props()
    register_sync()
    register_fiber_sync()
    register_muscle_sync()
    register_blob_sync()
    register_control_runtime()
    register_delete_reconcile()


def unregister():
    unregister_delete_reconcile()
    unregister_control_runtime()
    unregister_blob_sync()
    unregister_muscle_sync()
    unregister_fiber_sync()
    unregister_sync()
    unregister_scene_props()

    del bpy.types.Object.af_scp_system
    del bpy.types.Object.af_vcp_system
    del bpy.types.Object.af_shortcut_system

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
