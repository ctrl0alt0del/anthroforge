import bpy

from ..app.use_cases.blob_tools import select_blob_control


def _finish(operator, result):
    if result.message:
        operator.report({result.level}, result.message)
    return {"FINISHED"} if result.ok else {"CANCELLED"}


class AF_OT_SelectBlobControl(bpy.types.Operator):
    bl_idname = "af.select_blob_control"
    bl_label = "Select Blob Control Point"
    bl_options = {"REGISTER", "UNDO"}

    blob_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        return _finish(self, select_blob_control(context, self.blob_id))
