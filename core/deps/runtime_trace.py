import os
import time
from dataclasses import dataclass


_TRACE_ENV = "AF_DEPS_TRACE"
_TRACE_MIN_MS_ENV = "AF_DEPS_TRACE_MIN_MS"


@dataclass(frozen=True)
class TraceSession:
    enabled: bool
    min_ms: float
    profile: object
    started_at: float


def set_runtime_trace(enabled=True, min_ms=0.0):
    os.environ[_TRACE_ENV] = "1" if bool(enabled) else "0"
    os.environ[_TRACE_MIN_MS_ENV] = str(max(0.0, float(min_ms)))


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
    return _flag_enabled(scene) or _flag_enabled(root) or True


def trace_min_ms():
    try:
        return max(0.0, float(os.environ.get(_TRACE_MIN_MS_ENV, "0") or 0.0))
    except Exception:
        return 0.0


def phase_profile(enabled):
    return {"constraints": {}, "sync": {}, "post_sync": {}} if enabled else None


def trace_session(root=None, scene=None):
    enabled = trace_enabled(root=root, scene=scene)
    return TraceSession(enabled, trace_min_ms(), phase_profile(enabled), time.perf_counter())


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


def record_profile(profile, bucket, name, dt_ms):
    if profile is None:
        return
    items = profile.setdefault(bucket, {})
    items[name] = items.get(name, 0.0) + dt_ms


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
    if not (session.enabled and total_ms >= session.min_ms):
        return
    trace_line(_runtime_summary(total_ms, gate_meta, build.is_full, build.dirty, impacted, constraint_impacts))
    trace_line(_phase_summary(build_ms, impact_ms, constraint_ms, expand_ms, sync_ms))
    _trace_profile(session.profile)
