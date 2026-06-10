import bpy

from ..app.use_cases.blob_create import create_blob_vcp


def _finish(operator, result):
    if result.message:
        operator.report({result.level}, result.message)
    return {"FINISHED"} if result.ok else {"CANCELLED"}


class AF_OT_AddBlobVCP(bpy.types.Operator):
    bl_idname = "af.add_blob_vcp"
    bl_label = "Add Blob VCP"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _finish(self, create_blob_vcp(context))
