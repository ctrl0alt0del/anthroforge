bl_info = {
  "name": "AnthroForge",
  "author": "AnthroForge Team",
  "version": (0, 2, 0),
  "blender": (5, 0, 0),
  "location": "View3D > Sidebar > AnthroForge",
  "description": "Procedural anatomical construction system",
  "category": "Object",
}

import bpy

from .core.action_library_quick_hook import clear_quick_hook_sessions
from .core.scp_runtime.visibility import restore_all_scp_isolations

__addon_enabled__ = False

from .operators.create_root import AF_OT_CreateRoot
from .operators.add_scp import (
    AF_OT_AddSCP,
    AF_OT_ClearSCPChildAnchorLock,
    AF_OT_MoveSCPOriginToAttachment,
    AF_OT_SetSCPChildAnchorLock,
    AF_OT_SetSCPParent,
)
from .operators.tree import (
    AF_OT_ToggleSCPCollapse,
    AF_OT_ToggleSCPVisibility,
    AF_OT_CopySCPInTree,
    AF_OT_DeleteSCPInTree,
    AF_OT_DeleteVCPInTree,
    AF_OT_PromoteSCPInTree,
    AF_OT_SelectSCPInTree,
    AF_OT_ToggleVCPCollapse,
    AF_OT_SelectVCPInTree,
)
from .operators.add_fiber_vcp import AF_OT_AddFiberVCP
from .operators.fiber_proxy import (
    AF_OT_ConnectProxyVerticesWithFiber,
    AF_OT_CreateLoopFiberFromSelectedVertices,
    AF_OT_CreateSymmetricLoopFiberFromSelectedVertices,
)
from .operators.add_muscle_vcp import AF_OT_AddMuscleVCP
from .operators.fiber_surface import (
    AF_OT_CreateFiberSurface,
    AF_OT_CreateMuscleFromFiberSurface,
    AF_OT_ConvertMuscleToFiberSurface,
    AF_OT_RecomputeFiberSurface,
    AF_OT_SelectFiberSurfaceSources,
)
from .operators.add_blob_vcp import AF_OT_AddBlobVCP
from .operators.fiber_tools import (
    AF_OT_ClearFiberWarmStart,
    AF_OT_RecomputeFiber,
    AF_OT_RestoreLegacyFiber,
    AF_OT_AddFiberTouchPoint,
    AF_OT_RemoveFiberTouchPoint,
    AF_OT_MoveFiberTouchPoint,
)
from .operators.fiber_repair import AF_OT_ConfirmFiberRepairs, AF_OT_RepairFibers
from .operators.muscle_tools import (
    AF_OT_FlipMuscleNormals,
    AF_OT_SelectMuscleInflationCtrl,
)
from .operators.blob_tools import AF_OT_SelectBlobControl
from .operators.soft_tissue import (
    AF_OT_AddSoftTissueVCP,
    AF_OT_AssignSoftTissueTarget,
    AF_OT_ApplySoftTissuePreset,
    AF_OT_ClearSoftTissueTarget,
    AF_OT_DuplicateSoftTissueSnapshot,
    AF_OT_ConvertBlobToSoftTissue,
    AF_OT_RebindSoftTissue,
    AF_OT_RecomputeSoftTissue,
    AF_OT_SelectSoftTissueBase,
    AF_OT_SelectSoftTissueTarget,
)
from .operators.import_package import AF_OT_ImportPackage, AF_OT_ImportSCPDiff, AF_OT_ImportVCP
from .operators.proxy_view import AF_OT_ExitProxyView, AF_OT_SwitchToProxyView
from .operators.shortcuts import (
    AF_OT_AddDataShortcut,
    AF_OT_DeleteDataShortcut,
    AF_OT_EditShortcutOverride,
    AF_OT_ShortcutWizard,
)
from .operators.action_library import (
    AF_OT_CreateCurveLoftGroup,
    AF_OT_CreateLocalTransformProps,
    AF_OT_DisableAllFiberSurfaceRouting,
    AF_OT_NameQuickSCPHook,
    AF_OT_QuickFiber,
    AF_OT_RebindLocalTransformProps,
    AF_OT_RemoveLocalTransformProps,
    AF_OT_QuickSCPHook,
    AF_OT_SplitSCPByCorner,
)
from .operators.control_objects import (
    AFOTMarkSelectedSCPControlObject,
    AFOTToggleControlObjectApplyParent,
    AFOTToggleControlObjectShortcutAxis,
)
from .operators.scp_objects import (
    AF_OT_AddSCPBoundObject,
    AF_OT_CreateEmptySCP,
    AF_OT_RemoveSCPBoundObject,
    AF_OT_ToggleSCPBoundNativeParenting,
    AF_OT_ReplaceSCPTransformWithEmpty,
    AF_OT_SetSCPGeometryObject,
    AF_OT_SetSCPTransformObject,
)
from .operators.draft_skin import (
    AF_OT_CancelDraftSkin,
    AF_OT_ClearSkinCollagen,
    AF_OT_FillSkinCollagen,
    AF_OT_FinishSkinCollagenPaint,
    AF_OT_GenerateDraftSkin,
    AF_OT_PaintSkinCollagen,
    AF_OT_ResetDraftSkinSettings,
    AF_OT_SetSkinCollagenBrushWeight,
)
from .operators.topology import AF_OT_CancelTopology, AF_OT_GenerateTopology
from .operators.warm_update import AF_OT_CancelWarmUpdate, AF_OT_UpdateSkinTopology

from .ui.main_panel import AF_PT_MainPanel
from .ui.panels.create_panel import AF_PT_CreatePanel
from .ui.panels.tree_panel import AF_PT_TreePanel
from .ui.panels.edit_panel import AF_PT_EditPanel
from .ui.panels.fiber_edit_panel import AF_PT_FiberEditPanel
from .ui.panels.fiber_surface_edit_panel import AF_PT_FiberSurfaceEditPanel
from .ui.panels.fiber_create_panel import AF_PT_FiberCreatePanel
from .ui.panels.vcp_edit_panel import AF_PT_VCPEditPanel
from .ui.panels.blob_create_panel import AF_PT_BlobCreatePanel
from .ui.panels.blob_edit_panel import AF_PT_BlobEditPanel
from .ui.panels.soft_tissue_create_panel import AF_PT_SoftTissueCreatePanel
from .ui.panels.soft_tissue_edit_panel import AF_PT_SoftTissueEditPanel
from .ui.panels.shortcut_panel import AF_PT_ShortcutPanel, AF_UL_ShortcutWizardItems
from .ui.panels.action_library_panel import AF_PT_ActionLibraryPanel
from .ui.panels.control_objects_panel import AFPTControlObjectsPanel
from .ui.panels.draft_skin_panel import AF_PT_DraftSkinPanel
from .ui.panels.topology_panel import AF_PT_TopologyPanel
from .ui.panels.warm_update_panel import AF_PT_WarmUpdatePanel

from .properties.scp_properties import (
    AF_SCP_BoundObject_Property,
    AF_SCP_Property,
    AF_SCP_System_Property,
)
from .properties.vcp_properties import (
    AF_MuscleFiberRef_Property,
    AF_FiberSurfaceFiberRef_Property,
    AF_FiberSurfaceVCP_Property,
    AF_MuscleVCP_Property,
    AF_FiberTouchPoint_Property,
    AF_FiberLoopAnchor_Property,
    AF_FiberVCP_Property,
    AF_BlobVCP_Property,
    AF_SoftTissueAttachment_Property,
    AF_SoftTissueVCP_Property,
    AF_VCP_System_Property,
)
from .properties.shortcut_properties import (
    AF_DataShortcutOverride_Property,
    AF_DataShortcut_Property,
    AF_DataShortcut_System_Property,
    AF_ShortcutWizardItem_Property,
)
from .properties.draft_skin_properties import AF_DraftSkinSettings_Property
from .properties.topology_properties import AF_TopologySettings_Property

from .core.visualization.sync import register_sync, unregister_sync
from .core.visualization.fiber_sync import register_fiber_sync, unregister_fiber_sync
from .core.visualization.fiber_surface_sync import register_fiber_surface_sync, unregister_fiber_surface_sync
from .core.visualization.fiber_refinement import (
    register_fiber_refinement_runtime,
    unregister_fiber_refinement_runtime,
)
from .core.visualization.fiber_repair_runtime import (
    register_fiber_repair_runtime,
    unregister_fiber_repair_runtime,
)
from .core.visualization.fiber_anchor_overlay import (
    register_fiber_anchor_overlay,
    unregister_fiber_anchor_overlay,
)
from .core.visualization.fiber_cache_lifecycle import (
    register_fiber_cache_lifecycle,
    unregister_fiber_cache_lifecycle,
)
from .core.visualization.muscle_sync import register_muscle_sync, unregister_muscle_sync
from .core.visualization.blob_sync import register_blob_sync, unregister_blob_sync
from .core.visualization.soft_tissue_sync import register_soft_tissue_sync, unregister_soft_tissue_sync
from .core.visualization.sync_runner import (
    register_sync_runner_runtime,
    unregister_sync_runner_runtime,
)
from .core.visualization.control_runtime import (
    register_control_runtime,
    unregister_control_runtime,
)
from .core.visualization.delete_reconcile import (
    register_delete_reconcile,
    unregister_delete_reconcile,
)
from .core.scp_proxy import register_proxy_session_runtime, unregister_proxy_session_runtime
from .ui.scene_props import register_scene_props, unregister_scene_props

classes = (
    AF_OT_CreateRoot,
    AF_OT_AddSCP,
    AF_OT_SetSCPParent,
    AF_OT_MoveSCPOriginToAttachment,
    AF_OT_SetSCPChildAnchorLock,
    AF_OT_ClearSCPChildAnchorLock,
    AF_OT_GenerateDraftSkin,
    AF_OT_CancelDraftSkin,
    AF_OT_PaintSkinCollagen,
    AF_OT_FillSkinCollagen,
    AF_OT_ClearSkinCollagen,
    AF_OT_FinishSkinCollagenPaint,
    AF_OT_SetSkinCollagenBrushWeight,
    AF_OT_ResetDraftSkinSettings,
    AF_OT_GenerateTopology,
    AF_OT_CancelTopology,
    AF_OT_UpdateSkinTopology,
    AF_OT_CancelWarmUpdate,
    AF_OT_CreateEmptySCP,
    AF_OT_SetSCPTransformObject,
    AF_OT_ReplaceSCPTransformWithEmpty,
    AF_OT_SetSCPGeometryObject,
    AF_OT_AddSCPBoundObject,
    AF_OT_RemoveSCPBoundObject,
    AF_OT_ToggleSCPBoundNativeParenting,
    AF_OT_ToggleSCPCollapse,
    AF_OT_ToggleSCPVisibility,
    AF_OT_CopySCPInTree,
    AF_OT_DeleteSCPInTree,
    AF_OT_PromoteSCPInTree,
    AF_OT_SelectSCPInTree,
    AF_PT_MainPanel,
    AF_PT_CreatePanel,
    AF_PT_TreePanel,
    AF_PT_EditPanel,
    AF_PT_DraftSkinPanel,
    AF_PT_TopologyPanel,
    AF_PT_WarmUpdatePanel,

    AF_SCP_BoundObject_Property,
    AF_SCP_Property,
    AF_SCP_System_Property,
    AF_DraftSkinSettings_Property,
    AF_TopologySettings_Property,

    AF_OT_ClearFiberWarmStart,
    AF_OT_RecomputeFiber,
    AF_OT_RestoreLegacyFiber,
    AF_OT_AddFiberTouchPoint,
    AF_OT_RemoveFiberTouchPoint,
    AF_OT_MoveFiberTouchPoint,
    AF_OT_RepairFibers,
    AF_OT_ConfirmFiberRepairs,

    AF_PT_FiberEditPanel,
    AF_PT_FiberSurfaceEditPanel,
    AF_PT_FiberCreatePanel,

    AF_MuscleFiberRef_Property,
    AF_FiberSurfaceFiberRef_Property,
    AF_FiberSurfaceVCP_Property,
    AF_MuscleVCP_Property,
    AF_FiberTouchPoint_Property,
    AF_FiberLoopAnchor_Property,
    AF_FiberVCP_Property,
    AF_BlobVCP_Property,
    AF_SoftTissueAttachment_Property,
    AF_SoftTissueVCP_Property,
    AF_VCP_System_Property,

    AF_OT_AddFiberVCP,
    AF_OT_ConnectProxyVerticesWithFiber,
    AF_OT_CreateLoopFiberFromSelectedVertices,
    AF_OT_CreateSymmetricLoopFiberFromSelectedVertices,
    AF_OT_AddMuscleVCP,
    AF_OT_CreateFiberSurface,
    AF_OT_CreateMuscleFromFiberSurface,
    AF_OT_ConvertMuscleToFiberSurface,
    AF_OT_RecomputeFiberSurface,
    AF_OT_SelectFiberSurfaceSources,
    AF_OT_AddBlobVCP,
    AF_OT_AddSoftTissueVCP,
    AF_OT_AssignSoftTissueTarget,
    AF_OT_ApplySoftTissuePreset,
    AF_OT_ClearSoftTissueTarget,
    AF_OT_RecomputeSoftTissue,
    AF_OT_RebindSoftTissue,
    AF_OT_SelectSoftTissueBase,
    AF_OT_SelectSoftTissueTarget,
    AF_OT_DuplicateSoftTissueSnapshot,
    AF_OT_ConvertBlobToSoftTissue,
    AF_OT_ToggleVCPCollapse,
    AF_OT_SelectVCPInTree,
    AF_OT_DeleteVCPInTree,
    AF_PT_VCPEditPanel,
    AF_OT_FlipMuscleNormals,
    AF_OT_SelectMuscleInflationCtrl,
    AF_OT_SelectBlobControl,
    AF_PT_BlobEditPanel,
    AF_PT_SoftTissueCreatePanel,
    AF_PT_SoftTissueEditPanel,
    AF_OT_ImportPackage,
    AF_OT_ImportSCPDiff,
    AF_OT_ImportVCP,
    AF_OT_SwitchToProxyView,
    AF_OT_ExitProxyView,
    AF_DataShortcutOverride_Property,
    AF_DataShortcut_Property,
    AF_ShortcutWizardItem_Property,
    AF_DataShortcut_System_Property,
    AF_OT_AddDataShortcut,
    AF_OT_DeleteDataShortcut,
    AF_OT_EditShortcutOverride,
    AF_OT_ShortcutWizard,
    AF_OT_CreateCurveLoftGroup,
    AF_OT_CreateLocalTransformProps,
    AF_OT_DisableAllFiberSurfaceRouting,
    AF_OT_NameQuickSCPHook,
    AF_OT_QuickFiber,
    AF_OT_RebindLocalTransformProps,
    AF_OT_RemoveLocalTransformProps,
    AF_OT_QuickSCPHook,
    AF_OT_SplitSCPByCorner,
    AFOTMarkSelectedSCPControlObject,
    AFOTToggleControlObjectApplyParent,
    AFOTToggleControlObjectShortcutAxis,
    AF_UL_ShortcutWizardItems,
    AF_PT_ShortcutPanel,
    AF_PT_ActionLibraryPanel,
    AFPTControlObjectsPanel,
)


def _already_registered(error):
    return "already registered as a subclass" in str(error)


def _not_registered(error):
    text = str(error)
    return "missing bl_rna" in text or "not registered" in text


def _safe_register_class(cls):
    try:
        bpy.utils.register_class(cls)
    except ValueError as exc:
        if not _already_registered(exc):
            raise


def _safe_unregister_class(cls):
    try:
        bpy.utils.unregister_class(cls)
    except RuntimeError as exc:
        if not _not_registered(exc):
            raise


def _ensure_object_props():
    if not hasattr(bpy.types.Object, "af_scp_system"):
        bpy.types.Object.af_scp_system = bpy.props.PointerProperty(type=AF_SCP_System_Property)
    if not hasattr(bpy.types.Object, "af_vcp_system"):
        bpy.types.Object.af_vcp_system = bpy.props.PointerProperty(type=AF_VCP_System_Property)
    if not hasattr(bpy.types.Object, "af_shortcut_system"):
        bpy.types.Object.af_shortcut_system = bpy.props.PointerProperty(type=AF_DataShortcut_System_Property)
    if not hasattr(bpy.types.Object, "af_draft_skin_settings"):
        bpy.types.Object.af_draft_skin_settings = bpy.props.PointerProperty(type=AF_DraftSkinSettings_Property)
    if not hasattr(bpy.types.Object, "af_topology_settings"):
        bpy.types.Object.af_topology_settings = bpy.props.PointerProperty(type=AF_TopologySettings_Property)


def _drop_object_prop(name):
    if hasattr(bpy.types.Object, name):
        delattr(bpy.types.Object, name)


def _ensure_scene_props():
    if not hasattr(bpy.types.Scene, "af_attachments_enabled"):
        register_scene_props()


def _register_runtime_hooks():
    register_sync()
    register_fiber_sync(context_provider=lambda: bpy.context)
    register_fiber_cache_lifecycle()
    register_fiber_anchor_overlay(context_provider=lambda: bpy.context)
    register_fiber_surface_sync()
    register_fiber_refinement_runtime()
    register_fiber_repair_runtime()
    register_muscle_sync()
    register_blob_sync()
    register_soft_tissue_sync()
    register_sync_runner_runtime()
    register_control_runtime()
    register_delete_reconcile()
    register_proxy_session_runtime()


def _unregister_runtime_hooks():
    _shutdown_background_jobs()
    _clear_transient_sessions()
    _unregister_fiber_attachment_runtime()
    unregister_proxy_session_runtime()
    unregister_delete_reconcile()
    unregister_control_runtime()
    unregister_sync_runner_runtime()
    unregister_soft_tissue_sync()
    unregister_blob_sync()
    unregister_muscle_sync()
    unregister_fiber_surface_sync()
    unregister_fiber_sync()
    unregister_sync()


def _unregister_fiber_attachment_runtime():
    unregister_fiber_repair_runtime()
    unregister_fiber_cache_lifecycle()
    unregister_fiber_anchor_overlay()
    unregister_fiber_refinement_runtime()


def _shutdown_background_jobs():
    from .adapters.draft_skin.jobs import shutdown_jobs
    from .adapters.topology.jobs import shutdown_jobs as shutdown_topology_jobs
    from .adapters.warm_update.jobs import shutdown_jobs as shutdown_warm_jobs
    shutdown_warm_jobs()
    shutdown_topology_jobs()
    shutdown_jobs()


def _clear_transient_sessions():
    clear_quick_hook_sessions()
    restore_all_scp_isolations()


def _retrofit_loaded_shortcuts():
    from .core.shortcuts.owner_backsolve import retrofit_owner_backsolve_defaults
    from .core.utils import get_af_root
    for scene in tuple(getattr(bpy.data, "scenes", ()) or ()):
        root = get_af_root(scene)
        if root is not None:
            retrofit_owner_backsolve_defaults(root)


def register():
    global __addon_enabled__
    for cls in classes:
        _safe_register_class(cls)
    _ensure_object_props()
    _ensure_scene_props()
    if __addon_enabled__:
        return
    _register_runtime_hooks()
    _retrofit_loaded_shortcuts()
    __addon_enabled__ = True


def unregister():
    global __addon_enabled__
    if __addon_enabled__:
        _unregister_runtime_hooks()
        __addon_enabled__ = False
    unregister_scene_props()
    _drop_object_prop("af_scp_system")
    _drop_object_prop("af_vcp_system")
    _drop_object_prop("af_shortcut_system")
    _drop_object_prop("af_draft_skin_settings")
    _drop_object_prop("af_topology_settings")
    for cls in reversed(classes):
        _safe_unregister_class(cls)
