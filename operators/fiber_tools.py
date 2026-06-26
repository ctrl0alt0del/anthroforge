import bpy

from ..app.use_cases.fiber_tools import (
    add_dependent_loop,
    add_fiber_touch_point,
    add_loop_profile_key,
    clear_fiber_warm_start,
    recompute_fiber,
    remove_fiber_touch_point,
    remove_loop_profile_key,
)


def _finish(operator, result):
    if result.message:
        operator.report({result.level}, result.message)
    return {"FINISHED"} if result.ok else {"CANCELLED"}


class AF_OT_ClearFiberWarmStart(bpy.types.Operator):
    bl_idname = "af.clear_fiber_warm_start"
    bl_label = "Clear Warm Start"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        return _finish(self, clear_fiber_warm_start(context, self.fiber_id))


class AF_OT_RecomputeFiber(bpy.types.Operator):
    bl_idname = "af.recompute_fiber"
    bl_label = "Recompute Fiber"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        return _finish(self, recompute_fiber(context, self.fiber_id))


class AF_OT_AddFiberTouchPoint(bpy.types.Operator):
    bl_idname = "af.add_fiber_touch_point"
    bl_label = "Add Mid Touch Point"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        return _finish(self, add_fiber_touch_point(context, self.fiber_id))


class AF_OT_AddDependentLoopFiber(bpy.types.Operator):
    bl_idname = "af.add_dependent_loop_fiber"
    bl_label = "Add Dependent Loop"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        return _finish(self, add_dependent_loop(context, self.fiber_id))


class AF_OT_RemoveFiberTouchPoint(bpy.types.Operator):
    bl_idname = "af.remove_fiber_touch_point"
    bl_label = "Remove Mid Touch Point"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")
    touch_index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        return _finish(self, remove_fiber_touch_point(context, self.fiber_id, self.touch_index))


class AF_OT_AddLoopProfileKey(bpy.types.Operator):
    bl_idname = "af.add_loop_profile_key"
    bl_label = "Add Loop Profile Key"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        return _finish(self, add_loop_profile_key(context, self.fiber_id))


class AF_OT_RemoveLoopProfileKey(bpy.types.Operator):
    bl_idname = "af.remove_loop_profile_key"
    bl_label = "Remove Loop Profile Key"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")
    key_index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        return _finish(self, remove_loop_profile_key(context, self.fiber_id, self.key_index))
