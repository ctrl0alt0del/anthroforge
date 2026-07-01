import bpy

from ..app.use_cases.muscle_create import create_muscle_vcp


def _finish(operator, result):
    if result.message:
        operator.report({result.level}, result.message)
    return {"FINISHED"} if result.ok else {"CANCELLED"}


class AF_OT_AddMuscleVCP(bpy.types.Operator):
    bl_idname = "af.add_muscle_vcp"
    bl_label = "Create Muscle From Selected Fibers"
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty(name="Name", default="")
    closed_v: bpy.props.BoolProperty(name="Closed Ring (V)", default=False)
    use_mirrored_rows: bpy.props.BoolProperty(name="Use Mirrored Rows", default=False)

    def execute(self, context):
        return _finish(self, create_muscle_vcp(context, self.name, self.closed_v, self.use_mirrored_rows))
