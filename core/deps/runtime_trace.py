import os
import time
from collections import deque
from copy import deepcopy
from dataclasses import dataclass


_TRACE_ENV = "AF_DEPS_TRACE"
_TRACE_MIN_MS_ENV = "AF_DEPS_TRACE_MIN_MS"
_TELEMETRY_ENV = "AF_DEPS_TELEMETRY"
_TELEMETRY_MAX_RECORDS = 256
_SLICE_LIMITS_MS = (1.0, 2.0, 4.0, 8.0, 12.0, 16.0, 20.0, 33.0, 50.0, 100.0)
_DERIVED_COUNTERS = {"solves": ("solves", "fiber_solves"),
                     "iterations": ("iterations", "fiber_iterations"),
                     "collision_queries": ("collision_queries", "fiber_collision_queries"),
                     "writes": ("writes", "fiber_writes")}
_REQUEST_TELEMETRY = deque(maxlen=_TELEMETRY_MAX_RECORDS)
_ACTIVE_TELEMETRY = None
_REQUEST_SEQUENCE = 0


@dataclass(frozen=True)
class TraceSession:
    enabled: bool
    min_ms: float
    profile: object
    started_at: float


def set_runtime_trace(enabled=True, min_ms=0.0):
    os.environ[_TRACE_ENV] = "1" if bool(enabled) else "0"
    os.environ[_TRACE_MIN_MS_ENV] = str(max(0.0, float(min_ms)))


def set_request_telemetry(enabled=True):
    os.environ[_TELEMETRY_ENV] = "1" if bool(enabled) else "0"


def _flag_enabled(owner):
    try:
        return owner is not None and bool(owner.get("af_debug_deps_runtime", False))
    except Exception:
        return False


def trace_enabled(root=None, scene=None):
    raw = str(os.environ.get(_TRACE_ENV, "") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return _flag_enabled(scene) or _flag_enabled(root)


def telemetry_enabled(root=None, scene=None):
    raw = str(os.environ.get(_TELEMETRY_ENV, "") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return trace_enabled(root=root, scene=scene)


def trace_min_ms():
    try:
        return max(0.0, float(os.environ.get(_TRACE_MIN_MS_ENV, "0") or 0.0))
    except Exception:
        return 0.0


def phase_profile(enabled):
    return {"constraints": {}, "sync": {}, "post_sync": {}} if enabled else None


def trace_session(root=None, scene=None):
    enabled = trace_enabled(root=root, scene=scene)
    profiled = enabled or telemetry_enabled(root=root, scene=scene)
    return TraceSession(enabled, trace_min_ms(), phase_profile(profiled), time.perf_counter())


def timed_call(fn, *args):
    t0 = time.perf_counter()
    return fn(*args), (time.perf_counter() - t0) * 1000.0


def elapsed_ms(started_at):
    return (time.perf_counter() - started_at) * 1000.0


def sizes_map(by_type):
    out = {}
    for et, vals in dict(by_type or {}).items():
        if vals:
            out[str(et)] = len(set(vals or set()))
    return out


def trace_line(text):
    print(f"[AnthroForge][deps] {text}")


def clear_request_telemetry():
    global _ACTIVE_TELEMETRY
    _REQUEST_TELEMETRY.clear()
    _ACTIVE_TELEMETRY = None


def request_telemetry(clear=False):
    for record in _REQUEST_TELEMETRY:
        _finalize_request_record(record)
    records = tuple(deepcopy(record) for record in _REQUEST_TELEMETRY)
    if clear:
        clear_request_telemetry()
    return records


def current_request_telemetry():
    return _ACTIVE_TELEMETRY


def activate_request_telemetry(record):
    global _ACTIVE_TELEMETRY
    previous, _ACTIVE_TELEMETRY = _ACTIVE_TELEMETRY, record
    return previous


def restore_request_telemetry(record):
    global _ACTIVE_TELEMETRY
    _ACTIVE_TELEMETRY = record


def telemetry_cache_snapshot(record=None):
    target = _telemetry_target(record)
    if target is None:
        return
    target["cache_bytes"] = _cache_bytes()
    target["cache_delta_bytes"] = target["cache_bytes"] - target["cache_before_bytes"]


def begin_request_telemetry(request, queue_ms=0.0, root=None, scene=None):
    global _ACTIVE_TELEMETRY, _REQUEST_SEQUENCE
    if not telemetry_enabled(root=root, scene=scene):
        return None
    _REQUEST_SEQUENCE += 1
    record = _request_record(request, queue_ms, _REQUEST_SEQUENCE)
    record["cache_before_bytes"] = _cache_bytes()
    _ACTIVE_TELEMETRY = record
    return record


def finish_request_telemetry(record, run_ms=0.0):
    global _ACTIVE_TELEMETRY
    if record is None:
        return None
    record["run_ms"] = max(0.0, float(run_ms))
    record["cache_bytes"] = _cache_bytes()
    record["cache_delta_bytes"] = record["cache_bytes"] - record["cache_before_bytes"]
    _finalize_request_record(record)
    _REQUEST_TELEMETRY.append(record)
    _ACTIVE_TELEMETRY = None if _ACTIVE_TELEMETRY is record else _ACTIVE_TELEMETRY
    return record


def record_request_phases(**timings):
    if _ACTIVE_TELEMETRY is None:
        return
    phases = _ACTIVE_TELEMETRY["phase_ms"]
    for name, value in timings.items():
        phases[str(name)] = phases.get(str(name), 0.0) + max(0.0, float(value))


def record_request_driver_profile(profile):
    if _ACTIVE_TELEMETRY is None:
        return
    target = _ACTIVE_TELEMETRY["driver_ms"]
    for bucket, values in dict(profile or {}).items():
        rows = target.setdefault(str(bucket), {})
        for name, value in dict(values or {}).items():
            rows[str(name)] = rows.get(str(name), 0.0) + max(0.0, float(value))


def telemetry_count(name, amount=1, record=None):
    target = _ACTIVE_TELEMETRY if record is None else record
    if target is None:
        return
    counters = target["counters"]
    counters[str(name)] = counters.get(str(name), 0) + int(amount)


def telemetry_collision_query(amount=1):
    if _ACTIVE_TELEMETRY is None:
        return
    key = "_pending_collision_queries"
    _ACTIVE_TELEMETRY[key] = _ACTIVE_TELEMETRY.get(key, 0) + int(amount)


def telemetry_timing(name, milliseconds, record=None):
    target = _telemetry_target(record)
    if target is None:
        return
    timings = target["timings_ms"]
    timings[str(name)] = timings.get(str(name), 0.0) + max(0.0, float(milliseconds))


def telemetry_slice(milliseconds, phase="", record=None):
    target = _telemetry_target(record)
    if target is None:
        return
    value = max(0.0, float(milliseconds))
    slices = target["progressive_slices"]
    slices["count"], slices["total_ms"] = slices["count"] + 1, slices["total_ms"] + value
    slices["max_ms"] = max(slices["max_ms"], value)
    bucket = _slice_bucket(value)
    slices["histogram"][bucket] = slices["histogram"].get(bucket, 0) + 1
    if phase:
        slices["phases"][str(phase)] = slices["phases"].get(str(phase), 0) + 1


def record_profile(profile, bucket, name, dt_ms):
    if profile is None:
        return
    items = profile.setdefault(bucket, {})
    items[name] = items.get(name, 0.0) + dt_ms


def _request_record(request, queue_ms, sequence):
    payload = dict(getattr(request, "payload", {}) or {})
    source = str(getattr(request, "source", "unknown"))
    return {"request_id": int(sequence), "cause": str(payload.get("cause", source)), "source": source,
            "event": str(getattr(request, "event_type", "UPDATE")), "quality": str(getattr(request, "quality", "INTERACTIVE")),
            "full": bool(getattr(request, "full", False)), "aspects": _aspect_map(getattr(request, "dirty_aspects", {})),
            "queue_ms": max(0.0, float(queue_ms)), "run_ms": 0.0, "phase_ms": {}, "driver_ms": {}, "timings_ms": {},
            "counters": {}, "progressive_slices": _empty_slice_distribution()}


def _aspect_map(values):
    return {str(key): sorted(str(item) for item in set(items or ()))
            for key, items in dict(values or {}).items() if items}


def _empty_slice_distribution():
    return {"count": 0, "total_ms": 0.0, "max_ms": 0.0, "histogram": {}, "phases": {}}


def _slice_bucket(milliseconds):
    limit = next((value for value in _SLICE_LIMITS_MS if milliseconds <= value), None)
    return ">100" if limit is None else f"<={limit:g}"


def _cache_bytes():
    try:
        from ..utils import bounded_scene_cache_stats
        return int(bounded_scene_cache_stats().get("bytes", 0))
    except Exception:
        return 0


def _counter_value(record, *names):
    counters = record.get("counters", {})
    return sum(int(counters.get(name, 0)) for name in names)


def _telemetry_target(record):
    return _ACTIVE_TELEMETRY if record is None else record


def _finalize_request_record(record):
    _flush_collision_queries(record)
    for field, names in _DERIVED_COUNTERS.items():
        record[field] = _counter_value(record, *names)


def _flush_collision_queries(record):
    count = int(record.pop("_pending_collision_queries", 0))
    if count:
        counters = record["counters"]
        counters["fiber_collision_queries"] = counters.get("fiber_collision_queries", 0) + count


def _meta_fields(gate_meta):
    meta = dict(gate_meta or {})
    return str(meta.get("source", "unknown")), str(meta.get("event_type", "UPDATE"))


def _runtime_summary(total_ms, gate_meta, is_full, dirty, impacted, constraint_impacts):
    source, event_type = _meta_fields(gate_meta)
    return "runtime total={:.2f}ms source={} event={} full={} dirty={} impacted={} c_impacts={}".format(
        total_ms, source, event_type, bool(is_full), sizes_map(dirty), sizes_map(impacted), sizes_map(constraint_impacts)
    )


def _phase_summary(build_ms, impact_ms, constraint_ms, expand_ms, sync_ms):
    return "phases build={:.2f}ms impacted={:.2f}ms constraints={:.2f}ms c_expand={:.2f}ms sync={:.2f}ms".format(
        build_ms, impact_ms, constraint_ms, expand_ms, sync_ms
    )


def _trace_profile(profile):
    for bucket in ("constraints", "sync", "post_sync"):
        if profile and profile.get(bucket):
            trace_line(f"drivers.{bucket} {profile[bucket]}")


def emit_trace_report(session, gate_meta, build, impacted, constraint_impacts, build_ms, impact_ms, constraint_ms, expand_ms, sync_ms):
    total_ms = elapsed_ms(session.started_at)
    record_request_phases(build=build_ms, impacted=impact_ms, constraints=constraint_ms,
                          constraint_expand=expand_ms, sync=sync_ms)
    record_request_driver_profile(session.profile)
    if not (session.enabled and total_ms >= session.min_ms):
        return
    trace_line(_runtime_summary(total_ms, gate_meta, build.is_full, build.dirty, impacted, constraint_impacts))
    trace_line(_phase_summary(build_ms, impact_ms, constraint_ms, expand_ms, sync_ms))
    _trace_profile(session.profile)
