import bpy

from ..app.use_cases.fiber_create import create_fiber_vcp


def _finish(operator, result):
    if result.message:
        operator.report({result.level}, result.message)
    return {"FINISHED"} if result.ok else {"CANCELLED"}


class AF_OT_AddFiberVCP(bpy.types.Operator):
    bl_idname = "af.add_fiber_vcp"
    bl_label = "Add Fiber VCP"

    def execute(self, context):
        return _finish(self, create_fiber_vcp(context))
