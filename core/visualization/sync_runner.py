try:
    from ...app.context import addon_context
    from ...app.runtime_requests import runtime_request
    from ...app.runtime_sync import queue_runtime, run_runtime_now
except ImportError:
    from app.context import addon_context
    from app.runtime_requests import runtime_request
    from app.runtime_sync import queue_runtime, run_runtime_now
from ..deps import run_dependency_runtime


_RUNNING = False
_PENDING = []
_TIMER_ARMED = False


def _run_request(ctx, request):
    global _RUNNING
    if _RUNNING:
        return

    _RUNNING = True
    try:
        run_runtime_now(ctx, request, run_dependency_runtime)
    finally:
        _RUNNING = False


def _scheduler(ctx, request):
    _PENDING.append((ctx, request))
    _arm_timer()


def _arm_timer():
    global _TIMER_ARMED
    if _TIMER_ARMED:
        return
    _TIMER_ARMED = True
    import bpy
    bpy.app.timers.register(_flush_pending, first_interval=0.0)


def _next_request():
    return None if not _PENDING else _PENDING.pop(0)


def _flush_pending():
    global _TIMER_ARMED
    item = _next_request()
    if item is None:
        _TIMER_ARMED = False
        return None
    ctx, request = item
    _run_request(ctx, request)
    return 0.0


def _context(root=None, scene=None):
    return addon_context(root=root, scene=scene, scheduler=_scheduler)


def _request(dirty_hints=None, bake=False, source="manual", event_type="UPDATE", payload=None):
    return runtime_request(dirty_hints=dirty_hints, bake=bake, source=source, event_type=event_type, payload=payload)

def sync_from_dirty_hints(
    root=None, scene=None, dirty_hints=None, bake=False, source="manual", event_type="UPDATE", payload=None
):
    _run_request(_context(root=root, scene=scene), _request(dirty_hints, bake, source, event_type, payload))


def schedule_sync_from_dirty_hints(
    root=None, scene=None, dirty_hints=None, bake=False, source="manual", event_type="UPDATE", payload=None
):
    # Defer depsgraph-driven runtime work until Blender finishes the current evaluation pass.
    queue_runtime(_context(root=root, scene=scene), _request(dirty_hints, bake, source, event_type, payload))
