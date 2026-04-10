import os
import time

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
    ControlIntentDriver,
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


_TRACE_ENV = "AF_DEPS_TRACE"
_TRACE_MIN_MS_ENV = "AF_DEPS_TRACE_MIN_MS"


def set_runtime_trace(enabled=True, min_ms=0.0):
    """
    Enable/disable dependency runtime tracing through environment variables.
    Useful from Blender console during profiling sessions.
    """
    os.environ[_TRACE_ENV] = "1" if bool(enabled) else "0"
    os.environ[_TRACE_MIN_MS_ENV] = str(max(0.0, float(min_ms)))


def _trace_enabled(root=None, scene=None):
    raw = str(os.environ.get(_TRACE_ENV, "") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    try:
        if scene is not None and bool(scene.get("af_debug_deps_runtime", False)):
            return True
    except Exception:
        pass
    try:
        if root is not None and bool(root.get("af_debug_deps_runtime", False)):
            return True
    except Exception:
        pass
    return True


def _trace_min_ms():
    try:
        return max(0.0, float(os.environ.get(_TRACE_MIN_MS_ENV, "0") or 0.0))
    except Exception:
        return 0.0


def _sizes_map(by_type):
    out = {}
    for et, vals in dict(by_type or {}).items():
        n = len(set(vals or set()))
        if n > 0:
            out[str(et)] = n
    return out


def _trace_line(text):
    print(f"[AnthroForge][deps] {text}")


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


def _apply_constraint_drivers(
    root, scene, dirty, is_full, entity_sets, adjacency, scc_idx, scc_sizes, bake, gate_meta, profile=None
):
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
        t0 = time.perf_counter()
        out = d.apply_constraints(ctx) or {}
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if profile is not None:
            bucket = profile.setdefault("constraints", {})
            bucket[d.name] = bucket.get(d.name, 0.0) + dt_ms
        _merge_impacts(extra_impacts, out)

    return extra_impacts


def _run_sync_drivers(root, scene, is_full, impacted, bake, gate_meta, profile=None):
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
            t0 = time.perf_counter()
            d.sync(root=root, scene=scene, is_full=d_is_full, impacted=d_impacted, bake=bake)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            if profile is not None:
                bucket = profile.setdefault("sync", {})
                bucket[d.name] = bucket.get(d.name, 0.0) + dt_ms

    for d in get_dependency_drivers():
        t0 = time.perf_counter()
        d.post_sync(root=root, scene=scene, is_full=is_full, impacted=impacted, bake=bake)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if profile is not None:
            bucket = profile.setdefault("post_sync", {})
            bucket[d.name] = bucket.get(d.name, 0.0) + dt_ms


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
    trace_on = _trace_enabled(root=root, scene=scene)
    trace_min_ms = _trace_min_ms()
    profile = {"constraints": {}, "sync": {}, "post_sync": {}} if trace_on else None
    t_total = time.perf_counter()

    t0 = time.perf_counter()
    graph, entity_sets, adjacency, scc_idx, scc_sizes, dirty, is_full = _build_runtime_context(
        root, scene, dirty_hints, gate_meta=gate_meta
    )
    dt_build_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    impacted_sets = _compute_impacted_sets(graph, dirty, gate_meta=gate_meta)
    dt_impacted_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
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
        profile=profile,
    )
    dt_constraints_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    if constraint_impacts:
        starts = set()
        for et, ids in constraint_impacts.items():
            for eid in ids:
                starts.add((et, eid))
        if starts:
            impacted2 = graph.downstream_entities(starts)
            impacted2 |= starts
            _merge_impacts(impacted_sets, _impact_sets(impacted2))
    dt_constraints_expand_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    _run_sync_drivers(
        root=root,
        scene=scene,
        is_full=is_full,
        impacted=impacted_sets,
        bake=bake,
        gate_meta=gate_meta,
        profile=profile,
    )
    dt_sync_ms = (time.perf_counter() - t0) * 1000.0

    dt_total_ms = (time.perf_counter() - t_total) * 1000.0
    if trace_on and dt_total_ms >= trace_min_ms:
        meta = dict(gate_meta or {})
        source = str(meta.get("source", "unknown"))
        event_type = str(meta.get("event_type", "UPDATE"))
        _trace_line(
            "runtime total={:.2f}ms source={} event={} full={} dirty={} impacted={} c_impacts={}".format(
                dt_total_ms,
                source,
                event_type,
                bool(is_full),
                _sizes_map(dirty),
                _sizes_map(impacted_sets),
                _sizes_map(constraint_impacts),
            )
        )
        _trace_line(
            "phases build={:.2f}ms impacted={:.2f}ms constraints={:.2f}ms c_expand={:.2f}ms sync={:.2f}ms".format(
                dt_build_ms,
                dt_impacted_ms,
                dt_constraints_ms,
                dt_constraints_expand_ms,
                dt_sync_ms,
            )
        )
        if profile is not None:
            if profile.get("constraints"):
                _trace_line(f"drivers.constraints {profile['constraints']}")
            if profile.get("sync"):
                _trace_line(f"drivers.sync {profile['sync']}")
            if profile.get("post_sync"):
                _trace_line(f"drivers.post_sync {profile['post_sync']}")


# Register built-in drivers.
register_dependency_driver(RuntimeGraphDriver(), replace=True)
register_dependency_driver(SCPTransformIntentDriver(), replace=True)
register_dependency_driver(ControlIntentDriver(), replace=True)
register_dependency_driver(SCPConstraintDriver(), replace=True)
register_dependency_driver(SCPSyncDriver(), replace=True)
register_dependency_driver(FiberSyncDriver(), replace=True)
register_dependency_driver(MuscleSyncDriver(), replace=True)
register_dependency_driver(BlobSyncDriver(), replace=True)
register_dependency_driver(MirrorPostSyncDriver(), replace=True)
