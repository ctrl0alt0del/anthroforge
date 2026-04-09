from .runtime_graph import RuntimeGraph, tarjan_scc
from .drivers import (
    DependencyRuntimeContext,
    get_dependency_drivers,
    get_registered_entity_types,
    register_dependency_driver,
)
from .builtin_drivers import (
    RuntimeGraphDriver,
    SCPTransformIntentDriver,
    SCPConstraintDriver,
    SCPSyncDriver,
    FiberSyncDriver,
    MuscleSyncDriver,
    BlobSyncDriver,
    MirrorPostSyncDriver,
)
from .gates import (
    GateContext,
    evaluate_gates,
    PHASE_PRE_INGEST,
    PHASE_PRE_CONSTRAINT,
    PHASE_PRE_SYNC,
)

def _normalize_dirty_hints(entity_sets, dirty_hints):
    all_ids = {et: set(ids) for et, ids in entity_sets.items()}
    if not dirty_hints:
        return all_ids, True

    out = {}
    any_set = False
    for k in all_ids.keys():
        vals = set(dirty_hints.get(k, set()) or set()) & all_ids[k]
        out[k] = vals
        any_set = any_set or bool(vals)

    if not any_set:
        return all_ids, True
    return out, False


def _compute_scc_index(adjacency):
    sccs = tarjan_scc(adjacency)
    scc_index = {}
    scc_sizes = {}
    for i, comp in enumerate(sccs):
        for node in comp:
            scc_index[node] = i
        scc_sizes[i] = len(comp)
    return scc_index, scc_sizes


def _dirty_start_nodes(dirty):
    starts = set()
    for et in dirty.keys():
        for eid in dirty[et]:
            starts.add((et, eid))
    return starts


def _source_start_nodes(starts, gate_meta):
    payload = dict((gate_meta or {}).get("payload", {}) or {})
    by_type_raw = dict(payload.get("non_source_ids_by_type", {}) or {})
    by_type = {str(k): {str(x) for x in set(v or set())} for k, v in by_type_raw.items()}
    if not by_type:
        return set(starts)

    out = set()
    for et, eid in set(starts or set()):
        if str(eid) in by_type.get(str(et), set()):
            continue
        out.add((et, eid))
    return out


def _impact_sets(impacted):
    out = {et: set() for et in get_registered_entity_types()}
    for et, eid in impacted:
        if et in out:
            out[et].add(eid)
    return out


def _merge_impacts(base, extra):
    for et in set(base.keys()) | set(extra.keys()):
        base.setdefault(et, set())
        base[et] |= set(extra.get(et, set()) or set())


def _apply_constraint_drivers(root, scene, dirty, is_full, entity_sets, adjacency, scc_idx, scc_sizes, bake, gate_meta):
    gate_meta = gate_meta or {}
    extra_impacts = {et: set() for et in get_registered_entity_types()}

    for d in get_dependency_drivers():
        etypes = tuple(d.entity_types() or tuple())
        et = etypes[0] if len(etypes) == 1 else "*"

        source_ids = set()
        if et == "*":
            for ids in dirty.values():
                source_ids |= set(ids or set())
        else:
            source_ids = set(dirty.get(et, set()) or set())

        g = evaluate_gates(
            GateContext(
                phase=PHASE_PRE_CONSTRAINT,
                root=root,
                scene=scene,
                source=str(gate_meta.get("source", "unknown")),
                event_type=str(gate_meta.get("event_type", "UPDATE")),
                entity_type=et,
                entity_ids=source_ids,
                payload=dict(gate_meta.get("payload", {}) or {}),
            )
        )
        if not g.allow:
            continue

        d_dirty = {k: set(v or set()) for k, v in dirty.items()}
        if g.filtered_ids is not None:
            allowed = set(g.filtered_ids)
            for k in d_dirty.keys():
                d_dirty[k] &= allowed

        ctx = DependencyRuntimeContext(
            root=root,
            scene=scene,
            dirty=d_dirty,
            is_full=is_full,
            entity_sets=entity_sets,
            adjacency=adjacency,
            scc_idx=scc_idx,
            scc_sizes=scc_sizes,
            gate_meta=dict(gate_meta or {}),
            bake=bool(bake),
        )
        out = d.apply_constraints(ctx) or {}
        _merge_impacts(extra_impacts, out)

    return extra_impacts


def _run_sync_drivers(root, scene, is_full, impacted, bake, gate_meta):
    gate_meta = gate_meta or {}
    for d in get_dependency_drivers():
        etypes = tuple(d.entity_types() or tuple())
        if not etypes:
            et = "*"
            ids = set()
            for vals in impacted.values():
                ids |= set(vals or set())
        elif len(etypes) == 1:
            et = etypes[0]
            ids = set(impacted.get(et, set()) or set())
        else:
            et = "*"
            ids = set()
            for t in etypes:
                ids |= set(impacted.get(t, set()) or set())

        g = evaluate_gates(
            GateContext(
                phase=PHASE_PRE_SYNC,
                root=root,
                scene=scene,
                source=str(gate_meta.get("source", "unknown")),
                event_type=str(gate_meta.get("event_type", "UPDATE")),
                entity_type=et,
                entity_ids=ids,
                payload=dict(gate_meta.get("payload", {}) or {}),
            )
        )
        if not g.allow:
            continue

        d_impacted = {k: set(v or set()) for k, v in impacted.items()}
        d_is_full = bool(is_full)
        if g.filtered_ids is not None:
            allowed = set(g.filtered_ids)
            for k in d_impacted.keys():
                d_impacted[k] &= allowed
            d_is_full = False

        any_ids = any(bool(v) for v in d_impacted.values())
        if d_is_full or any_ids:
            d.sync(root=root, scene=scene, is_full=d_is_full, impacted=d_impacted, bake=bake)

    for d in get_dependency_drivers():
        d.post_sync(root=root, scene=scene, is_full=is_full, impacted=impacted, bake=bake)


def _build_runtime_context(root, scene, dirty_hints, gate_meta=None):
    gate_meta = gate_meta or {}

    graph = RuntimeGraph()
    entity_sets = {et: set() for et in get_registered_entity_types()}
    for d in get_dependency_drivers():
        d.build_graph(root, graph, entity_sets)

    adjacency = graph.entity_adjacency()
    scc_idx, scc_sizes = _compute_scc_index(adjacency)
    dirty, is_full = _normalize_dirty_hints(entity_sets, dirty_hints)

    # Let drivers inject delayed/derived dirty inputs before ingest gating.
    for d in get_dependency_drivers():
        if hasattr(d, "inject_delayed_dirty"):
            try:
                d.inject_delayed_dirty(root, dirty)
            except Exception:
                continue

    all_dirty_ids = set()
    for ids in dirty.values():
        all_dirty_ids |= set(ids or set())
    g = evaluate_gates(
        GateContext(
            phase=PHASE_PRE_INGEST,
            root=root,
            scene=scene,
            source=str(gate_meta.get("source", "unknown")),
            event_type=str(gate_meta.get("event_type", "UPDATE")),
            entity_type="*",
            entity_ids=all_dirty_ids,
            payload=dict(gate_meta.get("payload", {}) or {}),
        )
    )
    if not g.allow:
        for et in dirty.keys():
            dirty[et] = set()
        is_full = False
    elif g.filtered_ids is not None:
        allowed = set(g.filtered_ids)
        for et in dirty.keys():
            dirty[et] &= allowed
        is_full = False

    return graph, entity_sets, adjacency, scc_idx, scc_sizes, dirty, is_full


def _compute_impacted_sets(graph, dirty, gate_meta=None):
    starts = _dirty_start_nodes(dirty)
    source_starts = _source_start_nodes(starts, gate_meta)
    impacted = graph.downstream_entities(source_starts) if source_starts else set()
    impacted |= starts
    return _impact_sets(impacted)


def run_dependency_runtime(root, scene, dirty_hints=None, bake=False, gate_meta=None):
    graph, entity_sets, adjacency, scc_idx, scc_sizes, dirty, is_full = _build_runtime_context(
        root, scene, dirty_hints, gate_meta=gate_meta
    )

    impacted_sets = _compute_impacted_sets(graph, dirty, gate_meta=gate_meta)

    constraint_impacts = _apply_constraint_drivers(
        root=root,
        scene=scene,
        dirty=dirty,
        is_full=is_full,
        entity_sets=entity_sets,
        adjacency=adjacency,
        scc_idx=scc_idx,
        scc_sizes=scc_sizes,
        bake=bake,
        gate_meta=gate_meta,
    )

    if constraint_impacts:
        starts = set()
        for et, ids in constraint_impacts.items():
            for eid in ids:
                starts.add((et, eid))
        if starts:
            impacted2 = graph.downstream_entities(starts)
            impacted2 |= starts
            _merge_impacts(impacted_sets, _impact_sets(impacted2))

    _run_sync_drivers(root=root, scene=scene, is_full=is_full, impacted=impacted_sets, bake=bake, gate_meta=gate_meta)


# Register built-in drivers.
register_dependency_driver(RuntimeGraphDriver(), replace=True)
register_dependency_driver(SCPTransformIntentDriver(), replace=True)
register_dependency_driver(SCPConstraintDriver(), replace=True)
register_dependency_driver(SCPSyncDriver(), replace=True)
register_dependency_driver(FiberSyncDriver(), replace=True)
register_dependency_driver(MuscleSyncDriver(), replace=True)
register_dependency_driver(BlobSyncDriver(), replace=True)
register_dependency_driver(MirrorPostSyncDriver(), replace=True)
