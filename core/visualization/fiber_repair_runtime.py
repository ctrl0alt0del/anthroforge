"""Runtime orchestration for the Repair Fibers command."""

from dataclasses import dataclass
from time import monotonic

import bpy
from bpy.app.handlers import persistent

from ..vcp.fiber_pin_repair import (apply_fiber_pin_repair_plan, begin_fiber_pin_repair,
                                     fiber_pin_repair_signature)
from .fiber_refinement import (cancel_fiber_refinement, cancel_fiber_refinement_group,
                               fiber_refinement_group_state,
                               request_fiber_refinement_group)
from .fiber_sync import register_fiber_sync


_OPERATIONS = {}
_LAST_SUMMARIES = {}
_TOKEN = 0
_ACTIVE = {"SCANNING", "AWAITING_CONFIRMATION", "READY", "RECOMPUTING"}


@dataclass
class FiberRepairOperation:
    token: str
    scene_name: str
    root_name: str
    scene_uid: int
    root_uid: int
    session: object
    phase: str = "SCANNING"
    plan: object = None
    report: object = None
    group_token: str = ""
    error: str = ""
    last_stale_check: float = 0.0


def begin_fiber_repair(root, scene, depsgraph):
    global _TOKEN
    current = fiber_repair_state(root, scene)
    if current and current["active"]: raise RuntimeError("Repair Fibers is already running for this root.")
    _cancel_root_refinements(root, scene)
    session = begin_fiber_pin_repair(root, scene, depsgraph, register_fiber_sync()._solver)
    _TOKEN += 1; token = f"fiber-repair-{_TOKEN}"
    _OPERATIONS[_scope(root, scene)] = FiberRepairOperation(
        token, scene.name, root.name, _uid(scene), _uid(root), session)
    return token


def step_fiber_repair(token, budget_ms=12.0):
    operation = fiber_repair_operation(token)
    if operation is None or operation.phase != "SCANNING": return _snapshot(operation)
    if _scan_stale(operation): return _fail(operation, "Scene changed while scanning; retry Repair Fibers.")
    progress = operation.session.step(budget_ms)
    if progress["done"]: _finish_or_reject_scan(operation)
    return _snapshot(operation)


def apply_fiber_repair(token, depsgraph):
    operation = fiber_repair_operation(token)
    if operation is None or operation.phase not in {"READY", "AWAITING_CONFIRMATION"}: return False
    root, scene = _operation_data(operation)
    if root is None or operation.session.stale(): return bool(_fail(operation, "Repair plan became stale; retry."))
    solver = register_fiber_sync()._solver
    operation.report = apply_fiber_pin_repair_plan(root, scene, operation.plan, solver, depsgraph)
    operation.group_token = request_fiber_refinement_group(root, scene, operation.plan.fiber_ids, "FINAL")
    operation.phase = "RECOMPUTING"; return True


def cancel_fiber_repair(token):
    operation = fiber_repair_operation(token)
    if operation is None: return False
    if operation.phase == "SCANNING": operation.session.cancel()
    if operation.group_token: cancel_fiber_refinement_group(operation.group_token)
    operation.phase = "CANCELLED"; return True


def fiber_repair_operation(token):
    value = str(token or "")
    return next((row for row in _OPERATIONS.values() if row.token == value), None)


def fiber_repair_state(root, scene):
    operation = _OPERATIONS.get(_scope(root, scene))
    _refresh_group(operation)
    value = _snapshot(operation)
    if value is None: return {"active": False, "last_summary": _LAST_SUMMARIES.get(_scope(root, scene), "")}
    value["last_summary"] = _LAST_SUMMARIES.get(_scope(root, scene), "")
    return value


def risky_fiber_repairs(token):
    operation = fiber_repair_operation(token)
    return () if operation is None or operation.plan is None else operation.plan.risky


def _finish_scan(operation):
    operation.plan = operation.session.plan()
    operation.phase = "AWAITING_CONFIRMATION" if operation.plan.risky else "READY"


def _finish_or_reject_scan(operation):
    if _scan_stale(operation, force=True): _fail(operation, "Scene changed while scanning; retry Repair Fibers.")
    else: _finish_scan(operation)


def _scan_stale(operation, force=False):
    now = monotonic()
    if not force and now - operation.last_stale_check < 0.1: return False
    operation.last_stale_check = now
    return not _valid_operation(operation)


def _refresh_group(operation):
    if operation is None or operation.phase != "RECOMPUTING": return
    state = fiber_refinement_group_state(operation.group_token)
    if state is None: _fail(operation, "Fiber recompute group was lost."); return
    if state["done"]: _complete_operation(operation, state)


def _complete_operation(operation, group):
    operation.phase = "DONE"
    _LAST_SUMMARIES[(operation.scene_uid, operation.root_uid)] = _group_summary(group, True)


def _snapshot(operation):
    if operation is None: return None
    progress = operation.session.progress(); group = fiber_refinement_group_state(operation.group_token)
    plan = operation.plan; report = operation.report
    return {"token": operation.token, "phase": operation.phase, "active": operation.phase in _ACTIVE,
            "progress": progress, "planned": 0 if plan is None else len(plan.repairs),
            "invalid": len(operation.session.pins),
            "unresolved": 0 if plan is None else len(plan.failures), "risky": 0 if plan is None else len(plan.risky),
            "repaired": 0 if report is None else report.repaired_pins, "group": group,
            "error": operation.error, "summary": _summary(operation, group)}


def _summary(operation, group):
    if operation.phase == "SCANNING": return "Scanning Fiber pins…"
    if operation.phase == "AWAITING_CONFIRMATION": return "Repair plan needs confirmation."
    if operation.phase == "READY": return "Repair plan is ready."
    if operation.phase == "FAILED": return operation.error
    if operation.phase == "CANCELLED": return "Repair Fibers cancelled."
    if operation.phase == "RECOMPUTING": return _group_summary(group, False)
    return _group_summary(group, True)


def _group_summary(group, done):
    if not group: return "Recomputing Fibers…" if not done else "Repair Fibers finished."
    total = len(group["targets"]); complete = total - len(group["pending"])
    success, failures = len(group["committed"]), len(group["failures"])
    return f"{'Finished' if done else 'Recomputing'}: {complete}/{total}; {success} successful; {failures} failed."


def _fail(operation, message):
    operation.phase = "FAILED"; operation.error = str(message); return None


def _cancel_root_refinements(root, scene):
    for fiber in tuple(root.af_vcp_system.fibers): cancel_fiber_refinement(scene, fiber.id, mark_unknown=False)


def _valid_operation(operation):
    root, scene = _operation_data(operation)
    return root is not None and operation.session.signature == fiber_pin_repair_signature(root, scene)


def _operation_data(operation):
    scene = bpy.data.scenes.get(operation.scene_name)
    root = None if scene is None else scene.objects.get(operation.root_name)
    if root is None or _uid(scene) != operation.scene_uid or _uid(root) != operation.root_uid: return None, scene
    return root, scene


def _scope(root, scene):
    return _uid(scene), _uid(root)


def _uid(value):
    try: return int(getattr(value, "session_uid", 0) or value.as_pointer())
    except Exception: return 0


def register_fiber_repair_runtime():
    _add_handler(bpy.app.handlers.load_pre, _cancel_operations)
    _add_handler(bpy.app.handlers.undo_pre, _cancel_operations)


def unregister_fiber_repair_runtime():
    _cancel_operations()
    _drop_handler(bpy.app.handlers.load_pre, _cancel_operations)
    _drop_handler(bpy.app.handlers.undo_pre, _cancel_operations)


@persistent
def _cancel_operations(_unused=None):
    for operation in tuple(_OPERATIONS.values()): cancel_fiber_repair(operation.token)
    _OPERATIONS.clear()


def _add_handler(handlers, callback):
    if callback not in handlers: handlers.append(callback)


def _drop_handler(handlers, callback):
    while callback in handlers: handlers.remove(callback)
