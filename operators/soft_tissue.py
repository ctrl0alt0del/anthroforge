import bpy

from ..app.use_cases.soft_tissue_create import apply_soft_tissue_preset, create_soft_tissue_vcp
from ..app.use_cases.soft_tissue_tools import duplicate_soft_tissue_snapshot, recompute_soft_tissue, select_soft_tissue_base
from ..app.use_cases.soft_tissue_convert import convert_blob_to_soft_tissue


def _finish(operator, result):
    if result.message:
        operator.report({result.level}, result.message)
    return {"FINISHED"} if result.ok else {"CANCELLED"}


class AF_OT_AddSoftTissueVCP(bpy.types.Operator):
    bl_idname = "af.add_soft_tissue_vcp"
    bl_label = "Add Soft Tissue VCP"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _finish(self, create_soft_tissue_vcp(context))


class AF_OT_ApplySoftTissuePreset(bpy.types.Operator):
    bl_idname = "af.apply_soft_tissue_preset"
    bl_label = "Apply Soft Tissue Preset"
    bl_options = {"REGISTER", "UNDO"}
    preset: bpy.props.EnumProperty(items=tuple((x, x.replace("_", " ").title(), "") for x in ("CUSTOM", "CLOSED_BULK", "RIM", "LAYER", "POUCH")))

    def execute(self, context):
        return _finish(self, apply_soft_tissue_preset(context, self.preset))


class AF_OT_RecomputeSoftTissue(bpy.types.Operator):
    bl_idname = "af.recompute_soft_tissue"
    bl_label = "Recompute Soft Tissue"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _finish(self, recompute_soft_tissue(context))


class AF_OT_RebindSoftTissue(bpy.types.Operator):
    bl_idname = "af.rebind_soft_tissue"
    bl_label = "Rebind Soft Tissue"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _finish(self, recompute_soft_tissue(context, True))


class AF_OT_SelectSoftTissueBase(bpy.types.Operator):
    bl_idname = "af.select_soft_tissue_base"
    bl_label = "Select Soft Tissue Base"

    def execute(self, context):
        return _finish(self, select_soft_tissue_base(context))


class AF_OT_DuplicateSoftTissueSnapshot(bpy.types.Operator):
    bl_idname = "af.duplicate_soft_tissue_snapshot"
    bl_label = "Duplicate Final Mesh"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _finish(self, duplicate_soft_tissue_snapshot(context))


class AF_OT_ConvertBlobToSoftTissue(bpy.types.Operator):
    bl_idname = "af.convert_blob_to_soft_tissue"
    bl_label = "Convert Blob to Soft Tissue"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _finish(self, convert_blob_to_soft_tissue(context))
