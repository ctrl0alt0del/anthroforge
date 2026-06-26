from .drivers import get_dependency_drivers, get_registered_entity_types
from .gates import GateContext, PHASE_PRE_INGEST, evaluate_gates
from .runtime_graph import RuntimeGraph, tarjan_scc
from .runtime_models import RuntimeBuild

_GRAPH_CACHE = {}


def _empty_entity_sets():
    return {et: set() for et in get_registered_entity_types()}


def _graph_snapshot(root):
    graph = RuntimeGraph()
    entity_sets = _empty_entity_sets()
    for driver in get_dependency_drivers():
        driver.build_graph(root, graph, entity_sets)
    return graph, entity_sets


def compute_scc_index(adjacency):
    idx, sizes = {}, {}
    for i, comp in enumerate(tarjan_scc(adjacency)):
        for node in comp:
            idx[node] = i
        sizes[i] = len(comp)
    return idx, sizes


def normalize_dirty_hints(entity_sets, dirty_hints):
    all_ids = {et: set(ids) for et, ids in entity_sets.items()}
    if not dirty_hints:
        return all_ids, True
    out = {et: set(dirty_hints.get(et, set()) or set()) & ids for et, ids in all_ids.items()}
    if any(out.values()):
        return out, False
    return all_ids, True


def _inject_delayed_dirty(root, scene, dirty):
    for driver in get_dependency_drivers():
        if not hasattr(driver, "inject_delayed_dirty"):
            continue
        try:
            driver.inject_delayed_dirty(root, dirty, scene=scene)
        except Exception:
            continue


def _all_dirty_ids(dirty):
    ids = set()
    for values in dirty.values():
        ids |= set(values or set())
    return ids


def _ingest_context(root, scene, dirty, gate_meta):
    meta = dict(gate_meta or {})
    return GateContext(
        phase=PHASE_PRE_INGEST, root=root, scene=scene, source=str(meta.get("source", "unknown")),
        event_type=str(meta.get("event_type", "UPDATE")), entity_type="*", entity_ids=_all_dirty_ids(dirty),
        payload=dict(meta.get("payload", {}) or {}),
    )


def _clear_dirty(dirty):
    for et in dirty:
        dirty[et] = set()


def _filter_dirty(dirty, allowed):
    for et in dirty:
        dirty[et] &= allowed


def _apply_ingest_gate(root, scene, dirty, is_full, gate_meta):
    gate = evaluate_gates(_ingest_context(root, scene, dirty, gate_meta))
    if not gate.allow:
        _clear_dirty(dirty)
        return dirty, False
    if gate.filtered_ids is None:
        return dirty, is_full
    _filter_dirty(dirty, set(gate.filtered_ids))
    return dirty, False


def _root_key(root):
    try:
        return int(root.as_pointer())
    except Exception:
        return id(root)


def _driver_stamp():
    return tuple(str(getattr(driver, "name", type(driver).__name__)) for driver in get_dependency_drivers())


def _scp_stamp(root):
    items = getattr(getattr(root, "af_scp_system", None), "scps", ())
    return tuple((str(s.id or ""), str(getattr(s, "parent_id", "") or "")) for s in items)


def _touch_stamp(fiber):
    return tuple(str(getattr(tp, "parent_id", "") or "") for tp in getattr(fiber, "mid_touches", ()))


def _loop_anchor_stamp(fiber):
    return tuple((str(getattr(item, "parent_id", "") or ""), str(getattr(item, "attach_param", "") or "")) for item in getattr(fiber, "loop_anchors", ()))


def _loop_profile_stamp(fiber):
    return tuple((round(float(getattr(item, "t", 0.0)), 5), round(float(getattr(item, "delta_u", 0.0)), 5), round(float(getattr(item, "delta_v", 0.0)), 5)) for item in getattr(fiber, "loop_profile_keys", ()))


def _fiber_stamp(root):
    items = getattr(getattr(root, "af_vcp_system", None), "fibers", ())
    return tuple((str(f.id or ""), str(getattr(f, "topology_mode", "OPEN") or "OPEN"), str(getattr(f, "generation_mode", "SOLVED") or "SOLVED"), str(f.a_parent_id or ""), str(f.b_parent_id or ""), _touch_stamp(f), _loop_anchor_stamp(f), str(getattr(f, "driver_fiber_id", "") or ""), round(float(getattr(f, "loop_base_offset_u", 0.0)), 5), round(float(getattr(f, "loop_base_offset_v", 0.0)), 5), _loop_profile_stamp(f)) for f in items)


def _muscle_stamp(root):
    items = getattr(getattr(root, "af_vcp_system", None), "muscles", ())
    return tuple((str(m.id or ""), tuple(str(ref.fiber_id or "") for ref in getattr(m, "fiber_refs", ()))) for m in items)


def _blob_stamp(root):
    items = getattr(getattr(root, "af_vcp_system", None), "blobs", ())
    return tuple((str(b.id or ""), str(getattr(b, "attach_target_type", "") or ""), str(getattr(b, "attach_target_id", "") or "")) for b in items)


def _graph_stamp(root):
    return (_driver_stamp(), _scp_stamp(root), _fiber_stamp(root), _muscle_stamp(root), _blob_stamp(root))


def clear_runtime_context_cache(root=None):
    if root is None:
        _GRAPH_CACHE.clear()
        return
    _GRAPH_CACHE.pop(_root_key(root), None)


def _graph_data(root):
    graph, entity_sets = _graph_snapshot(root)
    adjacency = graph.entity_adjacency()
    scc_idx, scc_sizes = compute_scc_index(adjacency)
    return graph, entity_sets, adjacency, scc_idx, scc_sizes


def _cached_graph_data(root):
    key = _root_key(root)
    stamp = _graph_stamp(root)
    entry = _GRAPH_CACHE.get(key)
    if entry and entry.get("stamp") == stamp:
        return entry["data"]
    data = _graph_data(root)
    _GRAPH_CACHE[key] = {"stamp": stamp, "data": data}
    return data


def build_runtime_context(root, scene, dirty_hints, gate_meta=None):
    graph, entity_sets, adjacency, scc_idx, scc_sizes = _cached_graph_data(root)
    dirty, is_full = normalize_dirty_hints(entity_sets, dirty_hints)
    _inject_delayed_dirty(root, scene, dirty)
    dirty, is_full = _apply_ingest_gate(root, scene, dirty, is_full, gate_meta)
    return RuntimeBuild(graph, entity_sets, adjacency, scc_idx, scc_sizes, dirty, is_full)
