from .drivers import get_dependency_drivers, get_registered_entity_types
from .gates import GateContext, PHASE_PRE_INGEST, evaluate_gates
from .runtime_graph import RuntimeGraph, tarjan_scc
from .runtime_models import RuntimeBuild


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


def build_runtime_context(root, scene, dirty_hints, gate_meta=None):
    graph, entity_sets = _graph_snapshot(root)
    adjacency = graph.entity_adjacency()
    scc_idx, scc_sizes = compute_scc_index(adjacency)
    dirty, is_full = normalize_dirty_hints(entity_sets, dirty_hints)
    _inject_delayed_dirty(root, scene, dirty)
    dirty, is_full = _apply_ingest_gate(root, scene, dirty, is_full, gate_meta)
    return RuntimeBuild(graph, entity_sets, adjacency, scc_idx, scc_sizes, dirty, is_full)
