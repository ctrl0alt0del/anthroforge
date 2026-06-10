import bpy

from ..app.use_cases.create_root import run_create_root
class AF_OT_CreateRoot(bpy.types.Operator):
    bl_idname = "af.create_root"
    bl_label = "Create AnthroForge Root"
    bl_description = "Creates AnthroForge root empty object"

    def execute(self, context):
        if run_create_root(context.scene) is None:
            self.report({"WARNING"}, "AnthroForge Root already exists.")
            return {"CANCELLED"}
        self.report({"INFO"}, "AnthroForge Root created.")
        return {"FINISHED"}
