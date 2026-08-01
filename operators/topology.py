import bpy

from ..app.use_cases.topology import (
    abort_generation, cancel_generation, complete_generation, poll_generation,
    start_generation,
)


def _report(operator, result):
    if result.message:
        operator.report({result.level}, result.message)


class AF_OT_GenerateTopology(bpy.types.Operator):
    bl_idname = "af.generate_topology"
    bl_label = "Generate Topology"
    bl_description = "Generate guided field-aligned quad topology from the current draft skin"
    bl_options = {"REGISTER", "UNDO"}
    _timer = None

    def execute(self, context):
        result = start_generation(context)
        _report(self, result)
        if not result.ok:
            return {"CANCELLED"}
        self._timer = context.window_manager.event_timer_add(0.25, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            abort_generation(context)
            return self._close(context, {"CANCELLED"})
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        status = poll_generation(context)
        if status.state not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return {"PASS_THROUGH"}
        result = complete_generation(context, status)
        _report(self, result)
        return self._close(context, {"FINISHED"} if result.ok else {"CANCELLED"})

    def _close(self, context, result):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
        self._timer = None
        return result


class AF_OT_CancelTopology(bpy.types.Operator):
    bl_idname = "af.cancel_topology"
    bl_label = "Cancel Topology"
    bl_description = "Cancel the running topology job"

    def execute(self, context):
        result = cancel_generation(context)
        _report(self, result)
        return {"FINISHED"} if result.ok else {"CANCELLED"}
