import bpy

from ..app.use_cases.warm_update import (
    abort_update, cancel_update, complete_update, poll_update, start_update,
)


def _report(operator, result):
    if result.message:
        operator.report({result.level}, result.message)


class AF_OT_UpdateSkinTopology(bpy.types.Operator):
    bl_idname = "af.update_skin_topology"
    bl_label = "Update Skin & Topology"
    bl_description = "Warm-update outputs and automatically fall back to full generation when required"
    bl_options = {"REGISTER", "UNDO"}
    mode: bpy.props.EnumProperty(items=(("AUTO", "Update", ""),
                                        ("FORCE_SKIN", "Force Skin", ""),
                                        ("FORCE_TOPOLOGY", "Force Topology", ""),
                                        ("PREPARE", "Prepare Warm Start", "")), default="AUTO")
    _timer = None

    def execute(self, context):
        result = start_update(context, self.mode); _report(self, result)
        if not result.ok:
            return {"CANCELLED"}
        self._timer = context.window_manager.event_timer_add(0.25, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            abort_update(context); return self._close(context, {"CANCELLED"})
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        status = poll_update(context)
        if status.state not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return {"PASS_THROUGH"}
        result = complete_update(context, status); _report(self, result)
        return self._close(context, {"FINISHED"} if result.ok else {"CANCELLED"})

    def _close(self, context, result):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
        self._timer = None
        return result


class AF_OT_CancelWarmUpdate(bpy.types.Operator):
    bl_idname = "af.cancel_warm_update"
    bl_label = "Cancel Skin & Topology Update"

    def execute(self, context):
        result = cancel_update(context); _report(self, result)
        return {"FINISHED"} if result.ok else {"CANCELLED"}
