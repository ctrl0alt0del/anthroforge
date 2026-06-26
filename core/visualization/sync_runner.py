from dataclasses import dataclass

import bpy
from bpy.app.handlers import persistent

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


@dataclass(frozen=True)
class QueuedRuntime:
    scene_name: str = ""
    root_name: str = ""
    request: object = None


def _run_request(ctx, request):
    global _RUNNING
    if _RUNNING:
        return False
    _RUNNING = True
    try:
        run_runtime_now(ctx, request, run_dependency_runtime)
    finally:
        _rehide_proxy_session(ctx.root, ctx.scene)
        _RUNNING = False
    return True


def _rehide_proxy_session(root, scene):
    session = _active_proxy_session(root)
    if scene is not None and session:
        _proxy_rehide()(scene, session)


def _active_proxy_session(root):
    from ..scp_proxy.session import active_session
    return {} if root is None else active_session(root)


def _proxy_rehide():
    from ..scp_proxy.visibility import rehide_session
    return rehide_session


def _scheduler(ctx, request):
    _PENDING.append(_queue_item(ctx, request))
    _arm_timer()


def _arm_timer():
    global _TIMER_ARMED
    if _TIMER_ARMED:
        return
    _TIMER_ARMED = True
    bpy.app.timers.register(_flush_pending, first_interval=0.0)


def _next_request():
    return None if not _PENDING else _PENDING.pop(0)


def _peek_request():
    return None if not _PENDING else _PENDING[0]


def _queue_item(ctx, request):
    return QueuedRuntime(_obj_name(ctx.scene), _obj_name(ctx.root), request)


def _obj_name(obj):
    return "" if obj is None else str(getattr(obj, "name", "") or "")


def _resolve_item(item):
    scene = bpy.data.scenes.get(item.scene_name)
    root = bpy.data.objects.get(item.root_name)
    return _context(root=root, scene=scene), item.request


def _flush_pending():
    global _TIMER_ARMED
    item = _peek_request()
    if item is None:
        _TIMER_ARMED = False
        return None
    ctx, request = _resolve_item(item)
    if not _run_request(ctx, request):
        return 0.0
    _next_request()
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


def clear_pending_runtime(keep_timer=True):
    global _RUNNING, _TIMER_ARMED
    _PENDING.clear()
    _RUNNING = False
    if not keep_timer:
        _drop_timer()
        _TIMER_ARMED = False


@persistent
def _on_load_pre(_dummy):
    clear_pending_runtime()


@persistent
def _on_history_pre(_dummy):
    clear_pending_runtime()


def _drop_timer():
    active = getattr(bpy.app.timers, "is_registered", None)
    cancel = getattr(bpy.app.timers, "unregister", None)
    if callable(active) and callable(cancel) and active(_flush_pending):
        cancel(_flush_pending)


def _append_handler(seq, fn):
    if fn not in seq:
        seq.append(fn)


def _remove_handler(seq, fn):
    if fn in seq:
        seq.remove(fn)


def register_sync_runner_runtime():
    _append_handler(bpy.app.handlers.load_pre, _on_load_pre)
    _append_handler(bpy.app.handlers.undo_pre, _on_history_pre)
    _append_handler(bpy.app.handlers.redo_pre, _on_history_pre)


def unregister_sync_runner_runtime():
    clear_pending_runtime(keep_timer=False)
    _remove_handler(bpy.app.handlers.redo_pre, _on_history_pre)
    _remove_handler(bpy.app.handlers.undo_pre, _on_history_pre)
    _remove_handler(bpy.app.handlers.load_pre, _on_load_pre)
