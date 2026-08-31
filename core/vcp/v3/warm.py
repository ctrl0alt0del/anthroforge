"""Session-local V3 continuation state; never persisted as Fiber output."""

from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

from ..v2.contact_core import _resample, _span_counts


_WARM_LIMIT = 256
_WARM = OrderedDict()
_STATS = {"hits": 0, "misses": 0, "stores": 0}


@dataclass(frozen=True)
class V3WarmState:
    engine_version: str
    backend_version: str
    points: tuple
    pin_indices: tuple
    owners: tuple


def store_v3_warm_state(key, points, pin_indices, anchors, engine_version, backend_version):
    state = _warm_state(points, pin_indices, anchors, engine_version, backend_version)
    if state is None or not key: return False
    _WARM[key] = state; _WARM.move_to_end(key); _STATS["stores"] += 1
    while len(_WARM) > _WARM_LIMIT: _WARM.popitem(last=False)
    return True


def prepare_v3_warm_seed(key, enabled, count, anchors, engine_version, backend_version):
    if not enabled: return ()
    state = _WARM.get(key)
    if not _compatible(state, anchors, engine_version, backend_version):
        _STATS["misses"] += 1; return ()
    seed = _remap(state, max(int(count), len(anchors)), anchors)
    _WARM.move_to_end(key); _STATS["hits"] += 1
    return tuple(tuple(float(value) for value in row) for row in seed)


def clear_v3_warm_states(scene_id=None, root_id=None, fiber_ids=None):
    if scene_id is root_id is fiber_ids is None:
        _WARM.clear(); _reset_stats(); return
    wanted = None if fiber_ids is None else {str(value) for value in fiber_ids}
    for key in tuple(_WARM):
        if _matches(key, scene_id, root_id, wanted): _WARM.pop(key, None)


def v3_warm_cache_stats():
    return dict(_STATS, entries=len(_WARM), limit=_WARM_LIMIT)


def _warm_state(points, pins, anchors, engine, backend):
    rows = np.asarray(points, dtype=np.float64); indices = tuple(map(int, pins))
    owners = tuple(str(getattr(row, "owner_id", "") or "") for row in anchors)
    valid = rows.ndim == 2 and rows.shape[1:] == (3,) and np.isfinite(rows).all()
    valid = valid and len(indices) == len(owners) and indices and indices[0] == 0
    valid = valid and indices[-1] == len(rows) - 1 and tuple(sorted(indices)) == indices
    return V3WarmState(str(engine), str(backend), tuple(map(tuple, rows)), indices, owners) if valid else None


def _compatible(state, anchors, engine, backend):
    if state is None or state.engine_version != str(engine) or state.backend_version != str(backend):
        return False
    owners = tuple(str(getattr(row, "owner_id", "") or "") for row in anchors)
    return bool(len(owners) == len(state.pin_indices) and owners == state.owners)


def _remap(state, count, anchors):
    targets = _pin_indices(anchors, count); source = np.asarray(state.points, dtype=np.float64)
    rows = []
    for old, new in zip(zip(state.pin_indices[:-1], state.pin_indices[1:]),
                        zip(targets[:-1], targets[1:])):
        part = _resample(source[old[0]:old[1] + 1], new[1] - new[0] + 1)
        rows.extend(part if not rows else part[1:])
    result = np.ascontiguousarray(rows, dtype=np.float64)
    for index, anchor in zip(targets, anchors): result[index] = anchor.point
    return result


def _pin_indices(anchors, count):
    points = np.asarray([row.point for row in anchors], dtype=np.float64)
    counts = _span_counts(points, int(count) - 1)
    return tuple(map(int, np.r_[0, np.cumsum(counts)]))


def _matches(key, scene_id, root_id, wanted):
    if scene_id is not None and key[0] != str(scene_id): return False
    if root_id is not None and key[1] != str(root_id): return False
    return wanted is None or key[3] in wanted


def _reset_stats():
    for name in _STATS: _STATS[name] = 0
