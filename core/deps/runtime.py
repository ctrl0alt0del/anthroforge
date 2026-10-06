from .runtime_bootstrap import register_builtin_dependency_drivers
from .runtime_constraint_phase import apply_constraint_drivers
from .runtime_context_build import build_runtime_context, compute_scc_index, normalize_dirty_hints
from .runtime_impact import compute_impacted_sets, dirty_start_nodes, expand_constraint_impacts, impact_sets, merge_impacts, source_start_nodes
from .runtime_models import RuntimeBuild
from .control_work import finish_runtime_work
from .runtime_sync_phase import run_sync_drivers
from .runtime_trace import emit_trace_report, set_runtime_trace, sizes_map, timed_call, trace_enabled, trace_line, trace_min_ms, trace_session


def _trace_enabled(root=None, scene=None):
    return trace_enabled(root=root, scene=scene)


def _trace_min_ms():
    return trace_min_ms()


def _sizes_map(by_type):
    return sizes_map(by_type)


def _trace_line(text):
    trace_line(text)


def _normalize_dirty_hints(entity_sets, dirty_hints, full=None):
    return normalize_dirty_hints(entity_sets, dirty_hints, full)


def _compute_scc_index(adjacency):
    return compute_scc_index(adjacency)


def _dirty_start_nodes(dirty):
    return dirty_start_nodes(dirty)


def _source_start_nodes(starts, gate_meta):
    return source_start_nodes(starts, gate_meta)


def _impact_sets(impacted):
    return impact_sets(impacted)


def _merge_impacts(base, extra):
    merge_impacts(base, extra)


def _build_data(graph, entity_sets, adjacency, scc_idx, scc_sizes, dirty, is_full):
    return RuntimeBuild(graph, entity_sets, adjacency, scc_idx, scc_sizes, dirty, is_full)


def _apply_constraint_drivers(root, scene, dirty, is_full, entity_sets, adjacency, scc_idx, scc_sizes, bake, gate_meta, profile=None):
    build = _build_data(None, entity_sets, adjacency, scc_idx, scc_sizes, dirty, is_full)
    return apply_constraint_drivers(root, scene, build, bake, gate_meta, profile)


def _run_sync_drivers(root, scene, is_full, impacted, bake, gate_meta, profile=None):
    run_sync_drivers(root, scene, is_full, impacted, bake, gate_meta, profile)


def _build_runtime_context(root, scene, dirty_hints, gate_meta=None, full=None):
    build = build_runtime_context(root, scene, dirty_hints, gate_meta, full)
    return build.graph, build.entity_sets, build.adjacency, build.scc_idx, build.scc_sizes, build.dirty, build.is_full


def _compute_impacted_sets(graph, dirty, gate_meta=None):
    return compute_impacted_sets(graph, dirty, gate_meta)


def run_dependency_runtime(root, scene, dirty_hints=None, bake=False, gate_meta=None, full=None,
                           dirty_aspects=None, quality=""):
    gate_meta = _request_meta(gate_meta, full, dirty_aspects, quality, bake)
    trace = trace_session(root=root, scene=scene)
    build, build_ms = timed_call(build_runtime_context, root, scene, dirty_hints, gate_meta, full)
    impacted, impact_ms = timed_call(compute_impacted_sets, build.graph, build.dirty, gate_meta)
    gate_meta = _with_dirty_provenance(gate_meta, dirty_hints)
    c_impacts, c_ms = timed_call(apply_constraint_drivers, root, scene, build, bake, gate_meta, trace.profile)
    _, expand_ms = timed_call(expand_constraint_impacts, build.graph, impacted, c_impacts, gate_meta)
    _, sync_ms = timed_call(run_sync_drivers, root, scene, build.is_full, impacted, bake, gate_meta, trace.profile)
    emit_trace_report(trace, gate_meta, build, impacted, c_impacts, build_ms, impact_ms, c_ms, expand_ms, sync_ms)
    _notify_warnings(root, scene, build, impacted, gate_meta)
    finish_runtime_work(gate_meta)


def _notify_warnings(root, scene, build, impacted, meta):
    from ..visualization.warning_runtime import notify_action
    dirty = {key: set(values) for key, values in build.dirty.items()}
    for key, values in impacted.items():
        dirty.setdefault(key, set()).update(values)
    notify_action(root, scene, dirty, meta.get("event_type", ""), build.is_full)
    from ..muscle_pairs.runtime import notify
    notify(root, scene, dirty, meta.get("event_type", ""), build.is_full)


def _with_dirty_provenance(meta, dirty):
    values = dict(meta or {})
    rows = {} if dirty is None else dict(dirty or {})
    values["runtime_dirty_ids_by_type"] = {key: sorted(set(ids or ())) for key, ids in rows.items()}
    return values


def _request_meta(gate_meta, full, dirty_aspects, quality, bake):
    meta = dict(gate_meta or {})
    meta["full"] = bool(meta.get("full", False) if full is None else full)
    meta["dirty_aspects"] = dict(dirty_aspects or meta.get("dirty_aspects", {}) or {})
    mode = str(quality or meta.get("quality", "") or "").upper()
    meta["quality"] = "FINAL" if bake or mode in {"BAKE", "FINAL"} else "INTERACTIVE"
    return meta


register_builtin_dependency_drivers()
