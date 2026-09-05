"""Application boundary for the on-demand Repair Fibers workflow."""

from ..queries.root import root_for_context
from .results import failure, success


def begin_repair_fibers(context):
    root = root_for_context(context)
    if root is None: return failure("No active AnthroForge root.")
    if not len(root.af_vcp_system.fibers): return failure("The active root has no Fibers.")
    try: token = _runtime().begin_fiber_repair(root, context.scene, context.evaluated_depsgraph_get())
    except Exception as error: return failure(str(error))
    return success("Scanning Fiber pins…", value=token)


def apply_repair_fibers(context, token):
    depsgraph = context.evaluated_depsgraph_get()
    if not _runtime().apply_fiber_repair(token, depsgraph): return failure("The repair plan is unavailable or stale.")
    operation = _runtime().fiber_repair_operation(token)
    report = operation.report
    message = f"Repaired {report.repaired_pins} pins; recomputing all Fibers."
    return success(message, value=report)


def _runtime():
    from ...core.visualization import fiber_repair_runtime
    return fiber_repair_runtime
