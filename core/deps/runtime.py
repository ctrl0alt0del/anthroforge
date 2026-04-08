from collections import OrderedDict

from .runtime_graph import RuntimeGraph, tarjan_scc
from .adapters import build_runtime_graph, get_registered_entity_types
from .gates import (
    GateContext,
    evaluate_gates,
    PHASE_PRE_INGEST,
    PHASE_PRE_CONSTRAINT,
    PHASE_PRE_SYNC,
)
from ..constraints.scp_constraints import (
    evaluate_scp_constraints_runtime,
    apply_scp_input_write,
)
from ..visualization.sync import register_sync
from ..visualization.fiber_sync import register_fiber_sync
from ..visualization.muscle_sync import register_muscle_sync
from ..visualization.blob_sync import register_blob_sync
from ..visualization.mirror_sync import register_mirror_sync


_DELAYED_WRITES = {}
_ENTITY_SYNC_HANDLERS = OrderedDict()
_POST_SYNC_HANDLERS = []


def register_runtime_sync_handler(entity_type, handler, replace=False):
    et = str(entity_type or "").strip().upper()
    if not et:
        raise ValueError("entity_type is required")
    if not callable(handler):
        raise TypeError("handler must be callable")
    if et in _ENTITY_SYNC_HANDLERS and not replace:
        raise ValueError(f"sync handler already registered for {et}")
    _ENTITY_SYNC_HANDLERS[et] = handler


def register_post_sync_handler(handler):
    if not callable(handler):
        raise TypeError("handler must be callable")
    _POST_SYNC_HANDLERS.append(handler)


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


def _has_self_loop(adjacency, node):
    return node in adjacency.get(node, set())


def _apply_delayed_queue(root):
    if not _DELAYED_WRITES:
        return set()
    changed_scps = set()
    for (etype, eid, port), value in list(_DELAYED_WRITES.items()):
        if etype == "SCP":
            if apply_scp_input_write(root, eid, port, value):
                changed_scps.add(eid)
    _DELAYED_WRITES.clear()
    return changed_scps


def _dirty_start_nodes(dirty):
    starts = set()
    for et in dirty.keys():
        for eid in dirty[et]:
            starts.add((et, eid))
    return starts


def _impact_sets(impacted):
    out = {et: set() for et in get_registered_entity_types()}
    for et, eid in impacted:
        if et in out:
            out[et].add(eid)
    return out


def _update_delayed_writes(new_delayed):
    _DELAYED_WRITES.clear()
    _DELAYED_WRITES.update(new_delayed)


def _apply_constraints(
    root, scene, dirty, is_full, entity_sets, delayed_changed_scps, adjacency, scc_idx, scc_sizes, gate_meta=None
):
    gate_meta = gate_meta or {}
    scp_all = entity_sets.get("SCP", set())
    scp_dirty = dirty.get("SCP", set())
    changed_source_scps = set(scp_all) if is_full else set(scp_dirty)
    changed_source_scps |= delayed_changed_scps

    g = evaluate_gates(
        GateContext(
            phase=PHASE_PRE_CONSTRAINT,
            root=root,
            scene=scene,
            source=str(gate_meta.get("source", "unknown")),
            event_type=str(gate_meta.get("event_type", "UPDATE")),
            entity_type="SCP",
            entity_ids=changed_source_scps,
            payload=dict(gate_meta.get("payload", {}) or {}),
        )
    )
    if not g.allow:
        return set()
    if g.filtered_ids is not None:
        changed_source_scps = set(g.filtered_ids)

    if not changed_source_scps:
        return set()

    new_delayed = {}

    def delayed_writer(etype, eid, port, value):
        new_delayed[(etype, eid, port)] = value

    def is_cyclic_pair(src_id, dst_id):
        src_node = ("SCP", src_id)
        dst_node = ("SCP", dst_id)
        if src_node not in scc_idx or dst_node not in scc_idx:
            return False
        if scc_idx[src_node] != scc_idx[dst_node]:
            return False
        size = scc_sizes.get(scc_idx[src_node], 1)
        return size > 1 or _has_self_loop(adjacency, src_node)

    changed_dest_scps = evaluate_scp_constraints_runtime(
        root=root,
        changed_source_ids=changed_source_scps,
        is_cyclic_pair=is_cyclic_pair,
        delayed_writer=delayed_writer,
    )
    _update_delayed_writes(new_delayed)
    return changed_dest_scps


def _run_visual_sync(root, scene, is_full, impacted, bake, gate_meta=None):
    gate_meta = gate_meta or {}
    for et in get_registered_entity_types():
        handler = _ENTITY_SYNC_HANDLERS.get(et)
        if handler is None:
            continue
        target_ids = set(impacted.get(et, set()) or set())
        g = evaluate_gates(
            GateContext(
                phase=PHASE_PRE_SYNC,
                root=root,
                scene=scene,
                source=str(gate_meta.get("source", "unknown")),
                event_type=str(gate_meta.get("event_type", "UPDATE")),
                entity_type=et,
                entity_ids=target_ids,
                payload=dict(gate_meta.get("payload", {}) or {}),
            )
        )
        if not g.allow:
            continue
        if g.filtered_ids is not None:
            target_ids = set(g.filtered_ids)
        if is_full or target_ids:
            handler(root=root, scene=scene, is_full=is_full, target_ids=target_ids, bake=bake)

    for handler in _POST_SYNC_HANDLERS:
        handler(root=root, scene=scene, is_full=is_full, impacted=impacted, bake=bake)


def _build_runtime_context(root, scene, dirty_hints, gate_meta=None):
    gate_meta = gate_meta or {}
    delayed_changed_scps = _apply_delayed_queue(root)
    graph = RuntimeGraph()
    entity_sets = build_runtime_graph(root, graph)
    adjacency = graph.entity_adjacency()
    scc_idx, scc_sizes = _compute_scc_index(adjacency)
    dirty, is_full = _normalize_dirty_hints(entity_sets, dirty_hints)
    if "SCP" in dirty:
        dirty["SCP"] |= delayed_changed_scps

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

    return delayed_changed_scps, graph, entity_sets, adjacency, scc_idx, scc_sizes, dirty, is_full


def _compute_impacted_sets(graph, dirty):
    starts = _dirty_start_nodes(dirty)
    impacted = graph.downstream_entities(starts) if starts else set()
    impacted |= starts
    return _impact_sets(impacted)


def _merge_constraint_impacts(graph, impacted_sets, changed_dest_scps):
    if not changed_dest_scps:
        return
    impacted2 = graph.downstream_entities({("SCP", sid) for sid in changed_dest_scps})
    impacted2 |= {("SCP", sid) for sid in changed_dest_scps}
    extra = _impact_sets(impacted2)
    for et in impacted_sets.keys():
        impacted_sets[et] |= extra.get(et, set())


def run_dependency_runtime(root, scene, dirty_hints=None, bake=False, gate_meta=None):
    delayed_changed_scps, graph, entity_sets, adjacency, scc_idx, scc_sizes, dirty, is_full = _build_runtime_context(
        root, scene, dirty_hints, gate_meta=gate_meta
    )
    impacted_sets = _compute_impacted_sets(graph, dirty)
    changed_dest_scps = _apply_constraints(
        root=root,
        scene=scene,
        dirty=dirty,
        is_full=is_full,
        entity_sets=entity_sets,
        delayed_changed_scps=delayed_changed_scps,
        adjacency=adjacency,
        scc_idx=scc_idx,
        scc_sizes=scc_sizes,
        gate_meta=gate_meta,
    )
    _merge_constraint_impacts(graph, impacted_sets, changed_dest_scps)
    _run_visual_sync(root=root, scene=scene, is_full=is_full, impacted=impacted_sets, bake=bake, gate_meta=gate_meta)


def _sync_scp_handler(root, scene, is_full, target_ids, bake):
    if is_full:
        register_sync().sync_root_to_scene(root=root, scene=scene)
    else:
        register_sync().sync_root_to_scene(root=root, scene=scene, target_scp_ids=target_ids)


def _sync_fiber_handler(root, scene, is_full, target_ids, bake):
    if is_full:
        register_fiber_sync().sync_root_to_scene(root=root, scene=scene, bake=bake)
    else:
        register_fiber_sync().sync_root_to_scene(root=root, scene=scene, bake=bake, target_fiber_ids=target_ids)


def _sync_muscle_handler(root, scene, is_full, target_ids, bake):
    if is_full:
        register_muscle_sync().sync_root_to_scene(root=root, scene=scene)
    else:
        register_muscle_sync().sync_root_to_scene(root=root, scene=scene, target_muscle_ids=target_ids)


def _sync_blob_handler(root, scene, is_full, target_ids, bake):
    if is_full:
        register_blob_sync().sync_root_to_scene(root=root, scene=scene)
    else:
        register_blob_sync().sync_root_to_scene(root=root, scene=scene, target_blob_ids=target_ids)


def _sync_mirror_post_handler(root, scene, is_full, impacted, bake):
    register_mirror_sync().sync_root_to_scene(root=root, scene=scene)


register_runtime_sync_handler("SCP", _sync_scp_handler)
register_runtime_sync_handler("FIBER", _sync_fiber_handler)
register_runtime_sync_handler("MUSCLE", _sync_muscle_handler)
register_runtime_sync_handler("BLOB", _sync_blob_handler)
register_post_sync_handler(_sync_mirror_post_handler)
