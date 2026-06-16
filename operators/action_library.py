import bpy

from ..app.use_cases.local_transform_props import create_local_transform_props, rebind_local_transform_props, remove_local_transform_props


def _finish(op, context, action):
    ok, error = action(context)
    if ok:
        return {"FINISHED"}
    op.report({"ERROR"}, error)
    return {"CANCELLED"}


class AF_OT_CreateLocalTransformProps(bpy.types.Operator):
    bl_idname = "af.create_local_transform_props"
    bl_label = "Create Local Transform Properties"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _finish(self, context, create_local_transform_props)


class AF_OT_RebindLocalTransformProps(bpy.types.Operator):
    bl_idname = "af.rebind_local_transform_props"
    bl_label = "Rebind Local Transform Properties"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _finish(self, context, rebind_local_transform_props)


class AF_OT_RemoveLocalTransformProps(bpy.types.Operator):
    bl_idname = "af.remove_local_transform_props"
    bl_label = "Remove Local Transform Properties"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _finish(self, context, remove_local_transform_props)
