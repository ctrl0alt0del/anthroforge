"""Modal scan and undoable confirmation operators for Repair Fibers."""

import bpy

from ..app.queries.root import root_for_context
from ..app.use_cases.fiber_repair import apply_repair_fibers, begin_repair_fibers
from ..core.visualization.fiber_repair_runtime import (cancel_fiber_repair, fiber_repair_operation,
                                                       fiber_repair_state, risky_fiber_repairs,
                                                       step_fiber_repair)


class AF_OT_RepairFibers(bpy.types.Operator):
    bl_idname = "af.repair_fibers"
    bl_label = "Repair Fibers"
    bl_description = "Repair invalid authored Fiber pins, then recompute every Fiber in the active root"

    @classmethod
    def poll(cls, context):
        root = root_for_context(context)
        state = None if root is None else fiber_repair_state(root, context.scene)
        return bool(root and len(root.af_vcp_system.fibers) and not (state or {}).get("active"))

    def invoke(self, context, _event):
        result = begin_repair_fibers(context)
        if not result.ok: self.report({result.level}, result.message); return {"CANCELLED"}
        self.token = result.value; _begin_modal(self, context)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC": return _cancel_modal(self, context)
        if event.type != "TIMER": return {"PASS_THROUGH"}
        state = step_fiber_repair(self.token, 12.0); _update_modal(self, context, state)
        if state and state["phase"] == "SCANNING": return {"RUNNING_MODAL"}
        return _finish_scan_modal(self, context, state)

    def cancel(self, context):
        cancel_fiber_repair(getattr(self, "token", "")); _end_modal(self, context)


class AF_OT_ConfirmFiberRepairs(bpy.types.Operator):
    bl_idname = "af.confirm_fiber_repairs"
    bl_label = "Confirm Fiber Pin Repairs"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    token: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, _event):
        if not risky_fiber_repairs(self.token): return self.execute(context)
        return context.window_manager.invoke_props_dialog(self, width=620)

    def draw(self, context):
        _draw_risky_repairs(self.layout, context, self.token)

    def execute(self, context):
        result = apply_repair_fibers(context, self.token)
        self.report({result.level}, result.message)
        return {"FINISHED"} if result.ok else {"CANCELLED"}

    def cancel(self, _context):
        cancel_fiber_repair(self.token)


def _begin_modal(operator, context):
    manager = context.window_manager
    operator._timer = manager.event_timer_add(0.001, window=context.window)
    manager.progress_begin(0, 100); manager.modal_handler_add(operator)
    _status(context, "Repair Fibers: scanning current attachments (Esc to cancel)")


def _update_modal(operator, context, state):
    progress = (state or {}).get("progress", {})
    current, total = progress.get("current", 0), max(1, progress.get("total", 1))
    context.window_manager.progress_update(100.0 * current / total)
    if context.area is not None: context.area.tag_redraw()


def _finish_scan_modal(operator, context, state):
    _end_modal(operator, context)
    if not state or state["phase"] in {"FAILED", "CANCELLED"}:
        operator.report({"ERROR"}, (state or {}).get("error", "Repair scan cancelled.")); return {"CANCELLED"}
    _queue_confirmation(operator.token)
    return {"FINISHED"}


def _cancel_modal(operator, context):
    cancel_fiber_repair(operator.token); _end_modal(operator, context)
    operator.report({"INFO"}, "Repair Fibers cancelled; no attachments were changed.")
    return {"CANCELLED"}


def _end_modal(operator, context):
    timer = getattr(operator, "_timer", None)
    if timer is not None: context.window_manager.event_timer_remove(timer)
    operator._timer = None; context.window_manager.progress_end(); _status(context, None)


def _queue_confirmation(token):
    def launch():
        risky = bool(risky_fiber_repairs(token)); mode = "INVOKE_DEFAULT" if risky else "EXEC_DEFAULT"
        bpy.ops.af.confirm_fiber_repairs(mode, token=token)
        return None
    bpy.app.timers.register(launch, first_interval=0.0)


def _draw_risky_repairs(layout, context, token):
    layout.label(text="These repairs move a pin far or transfer it to another SCP.", icon="ERROR")
    names = _scp_names(root_for_context(context))
    for repair in risky_fiber_repairs(token): _draw_risky_row(layout, repair, names)
    layout.label(text="Cancel leaves every authored attachment unchanged.", icon="INFO")


def _draw_risky_row(layout, repair, names):
    pin, candidate = repair.pin, repair.candidate
    old = names.get(pin.owner, pin.owner); new = names.get(candidate.owner, candidate.owner)
    role = _role_label(pin.role, pin.index); distance = 1000.0 * candidate.displacement
    layout.label(text=f"{pin.fiber_id} · {role}: {old} → {new} · {distance:.2f} mm")


def _role_label(role, index):
    if role == "ENDPOINT_A": return "Endpoint A"
    if role == "ENDPOINT_B": return "Endpoint B"
    return f"{'Midpoint' if role == 'TOUCH' else 'Loop pin'} {index}"


def _scp_names(root):
    if root is None: return {}
    return {str(row.id): str(getattr(row, "name", "") or row.id) for row in root.af_scp_system.scps}


def _status(context, text):
    try: context.window.status_text_set(text)
    except Exception: pass
