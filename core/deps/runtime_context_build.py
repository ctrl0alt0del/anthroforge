from .drivers import get_dependency_drivers, get_registered_entity_types
from .gates import GateContext, PHASE_PRE_INGEST, evaluate_gates
from .runtime_graph import RuntimeGraph, tarjan_scc
from .runtime_models import RuntimeBuild

from . import relationship_cache as relationships
from .runtime_trace import telemetry_count, telemetry_timing
from time import perf_counter


def _empty_entity_sets():
    return {et: set() for et in get_registered_entity_types()}


def _graph_snapshot(root, capture=None):
    graph = RuntimeGraph()
    graph._captured_fiber_owners = None if capture is None else dict(capture.owners)
    entity_sets = _empty_entity_sets()
    for driver in get_dependency_drivers():
        driver.build_graph(root, graph, entity_sets)
    del graph._captured_fiber_owners
    return graph, entity_sets


def compute_scc_index(adjacency):
    idx, sizes = {}, {}
    for i, comp in enumerate(tarjan_scc(adjacency)):
        for node in comp:
            idx[node] = i
        sizes[i] = len(comp)
    return idx, sizes


def _full_requested(dirty_hints, full):
    if full is not None:
        return bool(full)
    marked = getattr(dirty_hints, "full", None)
    return bool(marked) if marked is not None else dirty_hints is None or not dirty_hints


def normalize_dirty_hints(entity_sets, dirty_hints, full=None):
    all_ids = {et: set(ids) for et, ids in entity_sets.items()}
    if _full_requested(dirty_hints, full):
        return all_ids, True
    hints = dict(dirty_hints or {})
    out = {et: set(hints.get(et, set()) or set()) & ids for et, ids in all_ids.items()}
    return out, False


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


def _graph_stamp(root, scene=None):
    return relationships.capture_relationships(root, scene)


def clear_runtime_context_cache(root=None):
    relationships.clear_relationship_cache(root)


def _graph_data(root, capture=None):
    graph, entity_sets = _graph_snapshot(root, capture)
    adjacency = graph.entity_adjacency()
    scc_idx, scc_sizes = compute_scc_index(adjacency)
    return graph, entity_sets, adjacency, scc_idx, scc_sizes


def _cached_graph_data(root, scene=None):
    started = perf_counter(); capture = _graph_stamp(root, scene)
    entry = relationships.graph_entry(capture)
    generation = relationships.reconcile_relationships(capture, entry)
    telemetry_timing("dependency_graph_key", (perf_counter() - started) * 1000)
    if entry is not None and entry[1] == generation:
        telemetry_count("dependency_graph_hits")
        return entry[2]
    telemetry_count("dependency_graph_misses"); telemetry_count("dependency_graph_rebuilds")
    data = _graph_data(root, capture)
    return relationships.store_graph(capture, generation, data)


def build_runtime_context(root, scene, dirty_hints, gate_meta=None, full=None):
    graph, entity_sets, adjacency, scc_idx, scc_sizes = _cached_graph_data(root, scene)
    dirty, is_full = normalize_dirty_hints(entity_sets, dirty_hints, full)
    _inject_delayed_dirty(root, scene, dirty)
    dirty, is_full = _apply_ingest_gate(root, scene, dirty, is_full, gate_meta)
    return RuntimeBuild(graph, entity_sets, adjacency, scc_idx, scc_sizes, dirty, is_full)
