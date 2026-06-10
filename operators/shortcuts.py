import bpy

from ..app.queries.root import has_root
from ..app.use_cases.shortcuts import add_shortcut_from_context, delete_shortcut_from_context


class AF_OT_AddDataShortcut(bpy.types.Operator):
    bl_idname = "af.add_data_shortcut"
    bl_label = "Add Data Shortcut"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not has_root(context):
            return {"CANCELLED"}
        ok, error = add_shortcut_from_context(context)
        if not ok:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        return {"FINISHED"}


class AF_OT_DeleteDataShortcut(bpy.types.Operator):
    bl_idname = "af.delete_data_shortcut"
    bl_label = "Delete Data Shortcut"
    bl_options = {"REGISTER", "UNDO"}

    shortcut_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        if not has_root(context):
            return {"CANCELLED"}
        return {"FINISHED"} if delete_shortcut_from_context(context, self.shortcut_id) else {"CANCELLED"}
