import bpy

from ..app.use_cases.muscle_tools import flip_muscle_normals, select_muscle_inflation_ctrl


def _finish(operator, result):
    if result.message:
        operator.report({result.level}, result.message)
    return {"FINISHED"} if result.ok else {"CANCELLED"}


class AF_OT_FlipMuscleNormals(bpy.types.Operator):
    bl_idname = "af.flip_muscle_normals"
    bl_label = "Swap Inflation Side"
    bl_description = "Reverse muscle inflation; branched muscles reverse the whole assembly"
    bl_options = {"REGISTER", "UNDO"}

    muscle_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        return _finish(self, flip_muscle_normals(context, self.muscle_id))


class AF_OT_SelectMuscleInflationCtrl(bpy.types.Operator):
    bl_idname = "af.select_muscle_inflation_ctrl"
    bl_label = "Select Max Inflation Point"
    bl_options = {"REGISTER", "UNDO"}

    muscle_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        return _finish(self, select_muscle_inflation_ctrl(context, self.muscle_id))
