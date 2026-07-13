import time

from .deps.runtime_trace import trace_enabled, trace_line
from .utils import scene_cache_get, scene_cache_set


_COUNTER_KEY = "af_perf_counters"


def perf_enabled(scene=None):
    return trace_enabled(scene=scene)


def perf_count(scene, name, amount=1):
    if not perf_enabled(scene):
        return
    data = dict(scene_cache_get(scene, _COUNTER_KEY) or {})
    data[str(name)] = int(data.get(str(name), 0)) + int(amount)
    scene_cache_set(scene, _COUNTER_KEY, data)


def perf_timer():
    return time.perf_counter()


def perf_time(scene, name, started_at):
    if perf_enabled(scene):
        ms = (time.perf_counter() - float(started_at)) * 1000.0
        trace_line(f"perf.{name} {ms:.2f}ms")
