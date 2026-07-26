import bpy

from ..app.queries.scp import active_scp_from_context
from ..app.use_cases.draft_skin import (
    abort_generation,
    cancel_generation,
    complete_generation,
    poll_generation,
    start_generation,
)
from ..core.draft_skin.constants import COLLAGEN_GROUP


def _report(operator, result):
    if result.message:
        operator.report({result.level}, result.message)


class AF_OT_GenerateDraftSkin(bpy.types.Operator):
    bl_idname = "af.generate_draft_skin"
    bl_label = "Generate Draft Skin"
    bl_description = "Generate a closed variable-collagen skin around finalized SCP and VCP surfaces"
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


class AF_OT_CancelDraftSkin(bpy.types.Operator):
    bl_idname = "af.cancel_draft_skin"
    bl_label = "Cancel Draft Skin"
    bl_description = "Cancel the running draft skin job"

    def execute(self, context):
        result = cancel_generation(context)
        _report(self, result)
        return {"FINISHED"} if result.ok else {"CANCELLED"}


class AF_OT_PaintSkinCollagen(bpy.types.Operator):
    bl_idname = "af.paint_skin_collagen"
    bl_label = "Paint Collagen"
    bl_description = "Create and activate the AnthroForge collagen vertex group"

    def execute(self, context):
        scp = active_scp_from_context(context)
        obj = None if scp is None else getattr(scp, "geometry_object_ref", None)
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "The active SCP has no mesh geometry.")
            return {"CANCELLED"}
        try:
            _enter_weight_paint(context, obj)
            scp.skin_collagen_mode = "PAINTED"
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


def _enter_weight_paint(context, obj):
    if context.object is not None and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for item in context.selected_objects:
        item.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    group = obj.vertex_groups.get(COLLAGEN_GROUP) or obj.vertex_groups.new(name=COLLAGEN_GROUP)
    obj.vertex_groups.active_index = group.index
    bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
