import bpy

from ..app.queries.scp import active_scp_from_context
from ..app.queries.root import root_for_context
from ..app.use_cases.draft_skin import (
    abort_generation,
    cancel_generation,
    complete_generation,
    poll_generation,
    start_generation,
)
from ..adapters.draft_skin.painting import (
    clear_map,
    fill_default,
    finish_paint,
    prepare_paint,
    set_brush_weight,
)
from ..core.draft_skin.settings import root_settings_percentages


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
    bl_description = "Activate absolute collagen weights on the source SCP"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _run_scp_action(self, context, prepare_paint)


class AF_OT_FillSkinCollagen(bpy.types.Operator):
    bl_idname = "af.fill_skin_collagen"
    bl_label = "Fill Default"
    bl_description = "Replace all painted collagen weights with the SCP default"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _run_scp_action(self, context, fill_default)


class AF_OT_ClearSkinCollagen(bpy.types.Operator):
    bl_idname = "af.clear_skin_collagen"
    bl_label = "Clear Painted Map"
    bl_description = "Remove painted weights and keep the SCP scalar as a uniform value"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _run_scp_action(self, context, clear_map)


class AF_OT_FinishSkinCollagenPaint(bpy.types.Operator):
    bl_idname = "af.finish_skin_collagen_paint"
    bl_label = "Finish Painting"
    bl_description = "Leave Weight Paint mode"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _run_scp_action(self, context, finish_paint)


class AF_OT_SetSkinCollagenBrushWeight(bpy.types.Operator):
    bl_idname = "af.set_skin_collagen_brush_weight"
    bl_label = "Set Collagen Brush Weight"
    bl_options = {"REGISTER", "UNDO"}

    weight: bpy.props.FloatProperty(min=0.0, max=1.0)

    def execute(self, context):
        set_brush_weight(context, self.weight)
        return {"FINISHED"}


class AF_OT_ResetDraftSkinSettings(bpy.types.Operator):
    bl_idname = "af.reset_draft_skin_settings"
    bl_label = "Reset Defaults"
    bl_description = "Restore the accepted draft-skin field parameters"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        root = root_for_context(context)
        if root is None:
            self.report({"ERROR"}, "No AnthroForge root is active.")
            return {"CANCELLED"}
        _reset_settings(root.af_draft_skin_settings)
        return {"FINISHED"}


def _run_scp_action(operator, context, action):
    scp = active_scp_from_context(context)
    if scp is None:
        operator.report({"ERROR"}, "No SCP is active.")
        return {"CANCELLED"}
    try:
        action(context, scp)
    except Exception as error:
        operator.report({"ERROR"}, str(error))
        return {"CANCELLED"}
    return {"FINISHED"}


def _reset_settings(settings):
    for name, value in root_settings_percentages().items():
        setattr(settings, name, value)
