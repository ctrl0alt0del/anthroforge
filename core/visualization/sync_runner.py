import os
import time
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
from ..deps.runtime_trace import begin_request_telemetry, finish_request_telemetry, trace_enabled, trace_line
from ..perf_trace import perf_count


_RUNNING = False
_PENDING = []
_TAIL_PENDING = []
_TIMER_ARMED = False
_TIMER_DUE_AT = 0.0
_ID_PAYLOAD_KEYS = ("scp_recapture_ids", "scp_apply_parent_ids", "scp_apply_target_ids",
                    "soft_tissue_recapture_ids", "soft_tissue_base_recapture_ids",
                    "soft_tissue_region_recapture_ids", "solved_fiber_ids")
_FALSE_VALUES = {"0", "false", "no", "off"}
_DEFER_ENV = "AF_DEPS_DEFER"
_DEFER_MS_ENV = "AF_DEPS_DEFER_MS"
_FIBER_DEFER_MS_ENV = "AF_FIBER_DEFER_MS"
_DEFER_MAX_MS_ENV = "AF_DEPS_DEFER_MAX_MS"
_DEFAULT_DEFER_MS = 75.0
_DEFAULT_FIBER_DEFER_MS = 125.0
_DEFAULT_MAX_MS = 0.0
_RETRY_SECONDS = 0.01
_MAX_TAIL_PASSES = 4


def runtime_request_active():
    return bool(_RUNNING)


@dataclass
class QueuedRuntime:
    scene_name: str = ""
    root_name: str = ""
    request: object = None
    first_seen_at: float = 0.0
    due_at: float = 0.0
    owner_ids: tuple = ()
    owner_refs: tuple = ()


def _run_request(ctx, request):
    global _RUNNING
    if _RUNNING:
        return False
    _RUNNING = True
    try:
        _run_request_chain(ctx, request)
    finally:
        _finish_request(ctx)
    return True


def _trace_request(ctx, request, queue_ms, elapsed):
    if not trace_enabled(root=ctx.root, scene=ctx.scene):
        return
    trace_line(f"request source={request.source} event={request.event_type} quality={request.quality} "
               f"full={request.full} aspects={request.dirty_aspects} queue={queue_ms:.2f}ms run={elapsed:.2f}ms")


def _request_seen(request):
    return float(getattr(request, "queued_at", 0.0) or _now())


def _run_request_chain(ctx, request):
    _run_one_request(ctx, request)
    for _index in range(_MAX_TAIL_PASSES):
        item = _pop_tail()
        if item is None:
            return
        _run_one_request(item[0], item[1])


def _run_one_request(ctx, request):
    if not _request_owners_alive(ctx, request):
        return
    queue_ms = 1000.0 * max(0.0, _now() - _request_seen(request))
    started = time.perf_counter()
    record = begin_request_telemetry(request, queue_ms, ctx.root, ctx.scene)
    try:
        run_runtime_now(ctx, request, run_dependency_runtime)
    finally:
        elapsed = 1000.0 * max(0.0, time.perf_counter() - started)
        finish_request_telemetry(record, elapsed)
        _trace_request(ctx, request, queue_ms, elapsed)


def _finish_request(ctx):
    global _RUNNING
    _reapply_scp_isolation(ctx.scene)
    _rehide_proxy_session(ctx.root, ctx.scene)
    _RUNNING = False
    _defer_tail_remainder()


def _reapply_scp_isolation(scene):
    from ..scp_runtime.visibility import reapply_scp_isolations
    if scene is not None:
        reapply_scp_isolations(scene)


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
    _enqueue_item(ctx, request)
    _arm_next_timer()


def _arm_next_timer():
    item = _next_due_item()
    if item is not None:
        _arm_timer(max(0.0, item.due_at - _now()))


def _arm_timer(first_interval=0.0):
    global _TIMER_ARMED, _TIMER_DUE_AT
    interval = max(0.0, float(first_interval))
    due_at = _now() + interval
    if _TIMER_ARMED and abs(due_at - _TIMER_DUE_AT) <= 1.0e-6:
        return
    if _TIMER_ARMED:
        _drop_timer()
    _TIMER_ARMED = True
    _TIMER_DUE_AT = due_at
    bpy.app.timers.register(_flush_pending, first_interval=interval)


def _now():
    return time.monotonic()


def _env_enabled(name, default=True):
    raw = str(os.environ.get(name, "") or "").strip().lower()
    return bool(default) if not raw else raw not in _FALSE_VALUES


def _env_seconds(name, default_ms):
    try:
        return max(0.0, float(os.environ.get(name, default_ms) or default_ms)) / 1000.0
    except Exception:
        return max(0.0, float(default_ms)) / 1000.0


def _defer_seconds(request=None):
    if request is not None and str(request.event_type) in {"FIBER_UPDATE", "FIBER_SOLVE_READY"}:
        return _env_seconds(_FIBER_DEFER_MS_ENV, _DEFAULT_FIBER_DEFER_MS)
    return _env_seconds(_DEFER_MS_ENV, _DEFAULT_DEFER_MS)


def _max_defer_seconds():
    return _env_seconds(_DEFER_MAX_MS_ENV, _DEFAULT_MAX_MS)


def _deferable(request):
    if not _env_enabled(_DEFER_ENV) or not request or request.bake:
        return False
    source = str(request.source)
    event = str(request.event_type)
    if event == "SCP_UPDATE":
        return source == "depsgraph"
    if event == "FIBER_UPDATE":
        return source in {"depsgraph", "property"}
    if event == "FIBER_SOLVE_READY":
        return source == "fiber_refinement"
    return event == "SOFT_TISSUE_UPDATE" and source in {"depsgraph", "property"}


def _enqueue_item(ctx, request):
    if not _request_owners_alive(ctx, request):
        return None
    item = _queue_item(ctx, request)
    if not _deferable(request):
        _PENDING.append(item)
        return item
    return _enqueue_deferred(ctx, item)


def _enqueue_deferred(ctx, item):
    idx = _coalesce_index(item)
    if idx is None:
        _PENDING.append(item)
        _count(ctx.scene, "scheduled")
        return item
    _PENDING[idx] = _merge_item(_PENDING[idx], item)
    _count(ctx.scene, "coalesced")
    return _PENDING[idx]


def _queue_item(ctx, request):
    started = _now()
    due_at = started + (_defer_seconds(request) if _deferable(request) else 0.0)
    refs = (ctx.scene, ctx.root) if 'muscle_control_input' in request.payload else ()
    owner_ids = tuple(_owner_key(owner) for owner in refs)
    return QueuedRuntime(_obj_name(ctx.scene), _obj_name(ctx.root), request, started, due_at, owner_ids, refs)


def _coalesce_index(item):
    key = _defer_key(item)
    for index, old in enumerate(_PENDING):
        if _deferable(old.request) and _defer_key(old) == key:
            return index
    return None


def _defer_key(item):
    from ..deps.muscle_control_intents import input_key
    req = item.request
    return (item.scene_name, item.root_name, str(req.source), str(req.event_type), item.owner_ids,
            input_key(req.payload.get('muscle_control_input')))


def _merge_item(old, new):
    request = _merge_request(old.request, new.request)
    due_at = _merge_due_at(old, new)
    return QueuedRuntime(old.scene_name, old.root_name, request, old.first_seen_at, due_at, old.owner_ids, old.owner_refs)


def _merge_due_at(old, new):
    max_wait = _max_defer_seconds()
    if max_wait <= 0.0:
        return new.due_at
    return min(new.due_at, old.first_seen_at + max_wait)


def _merge_request(old, new):
    dirty = _merge_dirty(old.dirty_hints, new.dirty_hints)
    payload = _merge_payload(old.payload, new.payload)
    aspects = _merge_aspects(old.dirty_aspects, new.dirty_aspects)
    queued = min(float(old.queued_at), float(new.queued_at))
    return runtime_request(dirty, old.bake or new.bake, new.source, new.event_type, payload,
                           old.full or new.full, aspects, _merged_quality(old, new), queued)


def _merge_aspects(old, new):
    out = {str(key): set(values or ()) for key, values in dict(old or {}).items()}
    for key, values in dict(new or {}).items():
        out.setdefault(str(key), set()).update(set(values or ()))
    return out


def _merged_quality(old, new):
    values = {str(old.quality).upper(), str(new.quality).upper()}
    return "FINAL" if values & {"BAKE", "FINAL"} else "INTERACTIVE"


def _merge_dirty(old, new):
    out = {str(k): set(v or set()) for k, v in dict(old or {}).items()}
    for key, values in dict(new or {}).items():
        out.setdefault(str(key), set()).update(set(values or set()))
    return out


def _payload_ids(payload, key):
    return {str(v) for v in set(dict(payload or {}).get(key, ()) or ()) if str(v or "")}


def _merge_payload(old, new):
    out = dict(old or {})
    out.update(dict(new or {}))
    for key in _ID_PAYLOAD_KEYS:
        if key in dict(old or {}) or key in dict(new or {}):
            out[key] = sorted(_payload_ids(old, key) | _payload_ids(new, key))
    if "non_source_ids_by_type" in out:
        out["non_source_ids_by_type"] = _merge_nested_payload_ids(old, new)
    return out


def _merge_nested_payload_ids(old, new):
    out = {}
    for payload in (old, new):
        for key, values in dict(dict(payload or {}).get("non_source_ids_by_type", {}) or {}).items():
            out.setdefault(str(key), set()).update(str(v) for v in set(values or ()) if str(v or ""))
    return {key: sorted(values) for key, values in out.items()}


def _obj_name(obj):
    return "" if obj is None else str(getattr(obj, "name", "") or "")


def _resolve_item(item):
    if item.owner_ids:
        return _scoped_item_context(item), item.request
    scene = bpy.data.scenes.get(item.scene_name)
    root = bpy.data.objects.get(item.root_name)
    return _context(root=root, scene=scene), item.request


def _scoped_item_context(item):
    scene, root = item.owner_refs
    return _context(root, scene) if _owners_alive(scene, root, item.owner_ids) else None


def _request_owners_alive(ctx, request):
    return 'muscle_control_input' not in request.payload or _owners_alive(ctx.scene, ctx.root)


def _owners_alive(scene, root, identities=()):
    try:
        return (scene is not None and root is not None and bpy.data.scenes.get(scene.name) == scene
                and bpy.data.objects.get(root.name) == root and scene.objects.get(root.name) == root
                and (not identities or identities == (_owner_key(scene), _owner_key(root))))
    except (ReferenceError, AttributeError, TypeError):
        return False


def _flush_pending():
    now = _now()
    if not _PENDING:
        return _timer_result(None, now)
    idx = _ready_index(now)
    if idx is None:
        return _wait_for_next(now)
    item = _PENDING[idx]
    ctx, request = _resolve_item(item)
    if not _valid_context(ctx):
        return _discard_item(idx, now)
    return _flush_ready_item(idx, ctx, request, now)


def _flush_ready_item(idx, ctx, request, now):
    try:
        if not _run_request(ctx, request):
            return _timer_result(_RETRY_SECONDS, now)
    except Exception:
        from ..deps.muscle_control_intents import input_record
        if input_record(request.payload.get('muscle_control_input')) is None:
            raise
        import traceback
        traceback.print_exc()
        _PENDING.pop(idx)
        return _next_timer(now)
    return _finish_item(idx, ctx.scene, now)


def _discard_item(idx, now):
    _PENDING.pop(idx)
    _count(None, "discarded")
    return _next_timer(now)


def _finish_item(idx, scene, now):
    _PENDING.pop(idx)
    _count(scene, "flushed")
    return _next_timer(now)


def _ready_index(now):
    ready = [(i, item.due_at) for i, item in enumerate(_PENDING)
             if item.due_at <= now and not _earlier_control_pending(item.request)]
    return None if not ready else min(ready, key=lambda value: value[1])[0]


def _valid_context(ctx):
    return bool(ctx and ctx.root is not None and ctx.scene is not None)


def _wait_for_next(now):
    item = _next_due_item()
    _count(None if item is None else bpy.data.scenes.get(item.scene_name), "delayed")
    return _timer_result(_next_delay(now), now)


def _next_timer(now):
    return _timer_result(None if not _PENDING else _next_delay(now), now)


def _next_due_item():
    eligible = [item for item in _PENDING if not _earlier_control_pending(item.request)]
    return None if not eligible else min(eligible, key=lambda item: item.due_at)


def _next_delay(now):
    item = _next_due_item()
    return 0.0 if item is None else max(0.0, item.due_at - now)


def _timer_result(delay, now):
    global _TIMER_ARMED, _TIMER_DUE_AT
    _TIMER_ARMED = delay is not None
    _TIMER_DUE_AT = 0.0 if delay is None else now + max(0.0, float(delay))
    return None if delay is None else max(0.0, float(delay))


def _count(scene, name):
    perf_count(scene, f"defer_{name}")
    if trace_enabled(scene=scene):
        trace_line(f"defer.{name} pending={len(_PENDING)}")


def _context(root=None, scene=None):
    return addon_context(root=root, scene=scene, scheduler=_scheduler)


def _request(dirty_hints=None, bake=False, source="manual", event_type="UPDATE", payload=None,
             full=None, dirty_aspects=None, quality=""):
    return runtime_request(dirty_hints, bake, source, event_type, payload, full, dirty_aspects, quality)


def _runtime_key(ctx, request):
    from ..deps.muscle_control_intents import input_key
    value = dict(request.payload or {}).get('muscle_control_input')
    return (_owner_key(ctx.scene), _owner_key(ctx.root), str(request.source), str(request.event_type), input_key(value))


def _owner_key(owner):
    value = getattr(owner, "session_uid", 0)
    if value:
        return int(value)
    try:
        return int(owner.as_pointer())
    except Exception:
        return id(owner)


def _enqueue_tail(ctx, request):
    if not _request_owners_alive(ctx, request):
        return
    if _earlier_control_pending(request):
        _scheduler(ctx, request)
        return
    key = _runtime_key(ctx, request)
    for index, item in enumerate(_TAIL_PENDING):
        if _runtime_key(item[0], item[1]) == key:
            _TAIL_PENDING[index] = (ctx, _merge_request(item[1], request))
            return
    _TAIL_PENDING.append((ctx, request))


def _earlier_control_pending(request):
    return control_input_pending(dict(request.payload or {}).get('muscle_control_input'))


def control_input_pending(value):
    from ..deps.muscle_control_intents import input_key, input_record
    if value is None or not _PENDING:
        return False
    record = input_record(value)
    if record is None:
        return False
    pending = (dict(item.request.payload or {}).get('muscle_control_input') for item in _PENDING)
    return any(old is not None and input_key(old)[:-1] == input_key(value)[:-1]
               and record.handled < old.revision < value.revision
               and old.revision != record.processing for old in pending)


def _pop_tail():
    if not _TAIL_PENDING:
        return None
    ctx, request = _TAIL_PENDING.pop(0)
    if _earlier_control_pending(request):
        _scheduler(ctx, request)
        return None
    return ctx, request


def _defer_tail_remainder():
    if not _TAIL_PENDING:
        return
    items, _TAIL_PENDING[:] = tuple(_TAIL_PENDING), []
    for ctx, request in items:
        _enqueue_item(ctx, request)
    _arm_next_timer()


def sync_from_dirty_hints(
    root=None, scene=None, dirty_hints=None, bake=False, source="manual", event_type="UPDATE", payload=None,
    full=None, dirty_aspects=None, quality=""
):
    ctx = _context(root=root, scene=scene)
    request = _request(dirty_hints, bake, source, event_type, payload, full, dirty_aspects, quality)
    return _dispatch_runtime(ctx, request)


def _dispatch_runtime(ctx, request):
    from ..deps.muscle_control_intents import note_runtime_request
    note_runtime_request(request)
    if _RUNNING:
        _enqueue_tail(ctx, request)
        return False
    if _earlier_control_pending(request):
        _scheduler(ctx, request)
        return False
    return _run_request(ctx, request)


def schedule_sync_from_dirty_hints(
    root=None, scene=None, dirty_hints=None, bake=False, source="manual", event_type="UPDATE", payload=None,
    full=None, dirty_aspects=None, quality=""
):
    # Defer depsgraph-driven runtime work until Blender finishes the current evaluation pass.
    request = _request(dirty_hints, bake, source, event_type, payload, full, dirty_aspects, quality)
    from ..deps.muscle_control_intents import note_runtime_request
    note_runtime_request(request)
    queue_runtime(_context(root=root, scene=scene), request)


def clear_pending_runtime(keep_timer=True):
    global _RUNNING, _TIMER_ARMED, _TIMER_DUE_AT
    from ..deps.muscle_control_intents import reset_control_inputs
    from ..deps.runtime_intents import clear_muscle_control_intents
    reset_control_inputs()
    clear_muscle_control_intents()
    _PENDING.clear()
    _TAIL_PENDING.clear()
    _RUNNING = False
    if not keep_timer:
        _drop_timer()
        _TIMER_ARMED = False
        _TIMER_DUE_AT = 0.0


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
