import bpy
from ..app.queries.root import root_for_context


class AF_OT_UpdateFinalSkin(bpy.types.Operator):
    bl_idname = "af.update_final_skin"
    bl_label = "Update Now"
    bl_options = {"REGISTER"}

    def execute(self, context):
        from ..adapters.deformation.runtime import enqueue
        root = root_for_context(context)
        if root is None: return {"CANCELLED"}
        enqueue(root,context.scene,True)
        return {"FINISHED"}


class AF_OT_CancelFinalSkin(bpy.types.Operator):
    bl_idname = "af.cancel_final_skin"
    bl_label = "Cancel"

    def execute(self, context):
        from ..adapters.deformation.runtime import QUEUE
        from ..core.warnings.session import id_token
        root = root_for_context(context)
        if root is not None: QUEUE.cancel(id_token(root))
        return {"FINISHED"}


class AF_OT_InitializeFinalSkin(bpy.types.Operator):
    bl_idname = "af.initialize_final_skin"
    bl_label = "Initialize Deformation Reference"
    bl_options = {"REGISTER"}

    def execute(self, context):
        from ..adapters.deformation.runtime import initialize
        try:
            initialize(root_for_context(context),context.scene)
            return {"FINISHED"}
        except Exception as error:
            self.report({"ERROR"},str(error)); return {"CANCELLED"}


CLASSES = (AF_OT_UpdateFinalSkin,AF_OT_CancelFinalSkin,AF_OT_InitializeFinalSkin)


def register():
    for cls in CLASSES: bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES): bpy.utils.unregister_class(cls)
