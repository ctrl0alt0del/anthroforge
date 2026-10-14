"""Domain adapters are registered at startup; the issue core knows none of them."""
import bpy
from ..core.warnings import session
from ..core.issues.resolution import Solver


def register():
    system = session.SYSTEM
    if "FIBER" not in system.presentation.targets:
        system.presentation.register_target("FIBER", _select_fiber)
    if "repair_fibers" not in system.resolution.solvers:
        system.resolution.register(Solver("repair_fibers", "Repair Fibers (whole root)",
            ("FIBER_INVALID_HARD_ANCHOR",), _applicable, _repair, _cancel, _poll))


def unregister():
    session.SYSTEM.presentation.targets.clear()
    session.SYSTEM.resolution.solvers.clear()


def _select_fiber(issue, context):
    from ..core.visualization.warning_selection import select_warning
    return select_warning(context, issue.id)


def _applicable(issue, context):
    from ..core.visualization.warning_runtime import resolve_root
    scene, root = resolve_root(issue.entity.scope)
    return bool(context is not None and context.window is not None and root is not None)


def _repair(issue, context):
    from ..core.visualization.warning_runtime import ensure_timer
    if not _select_fiber(issue, context):
        raise ValueError("Fiber target is no longer current; recheck before repair")
    ensure_timer()
    return bpy.ops.af.repair_fibers("INVOKE_DEFAULT")


def _state(issue):
    from ..core.visualization.warning_runtime import resolve_root
    from ..core.visualization.fiber_repair_runtime import fiber_repair_state
    scene, root = resolve_root(issue.entity.scope)
    return {"phase": "CANCELLED"} if root is None else fiber_repair_state(root, scene)


def _poll(issue, context):
    return _state(issue).get("phase", "CANCELLED")


def _cancel(issue, context):
    from ..core.visualization.fiber_repair_runtime import cancel_fiber_repair
    cancel_fiber_repair(_state(issue).get("token", ""))
