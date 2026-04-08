from .runtime_graph import RuntimeGraph, tarjan_scc
from .adapters import build_runtime_graph
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


def _collect_all_ids(root):
    return {
        "SCP": {s.id for s in root.af_scp_system.scps},
        "FIBER": {f.id for f in root.af_vcp_system.fibers},
        "MUSCLE": {m.id for m in root.af_vcp_system.muscles},
        "BLOB": {b.id for b in root.af_vcp_system.blobs},
    }


def _normalize_dirty_hints(root, dirty_hints):
    all_ids = _collect_all_ids(root)
    if not dirty_hints:
        return all_ids, True

    out = {}
    any_set = False
    for k in ("SCP", "FIBER", "MUSCLE", "BLOB"):
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
    for et in ("SCP", "FIBER", "MUSCLE", "BLOB"):
        for eid in dirty[et]:
            starts.add((et, eid))
    return starts


def _impact_sets(impacted):
    return {
        "SCP": {eid for et, eid in impacted if et == "SCP"},
        "FIBER": {eid for et, eid in impacted if et == "FIBER"},
        "MUSCLE": {eid for et, eid in impacted if et == "MUSCLE"},
        "BLOB": {eid for et, eid in impacted if et == "BLOB"},
    }


def _update_delayed_writes(new_delayed):
    _DELAYED_WRITES.clear()
    _DELAYED_WRITES.update(new_delayed)


def _apply_constraints(root, dirty, is_full, entity_sets, delayed_changed_scps, adjacency, scc_idx, scc_sizes):
    changed_source_scps = set(entity_sets["SCP"]) if is_full else set(dirty["SCP"])
    changed_source_scps |= delayed_changed_scps
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


def _run_visual_sync(root, scene, is_full, impacted, bake):
    if is_full:
        register_sync().sync_root_to_scene(root=root, scene=scene)
    elif impacted["SCP"]:
        register_sync().sync_root_to_scene(root=root, scene=scene, target_scp_ids=impacted["SCP"])

    if is_full:
        register_fiber_sync().sync_root_to_scene(root=root, scene=scene, bake=bake)
    elif impacted["FIBER"]:
        register_fiber_sync().sync_root_to_scene(
            root=root, scene=scene, bake=bake, target_fiber_ids=impacted["FIBER"]
        )

    if is_full:
        register_muscle_sync().sync_root_to_scene(root=root, scene=scene)
    elif impacted["MUSCLE"]:
        register_muscle_sync().sync_root_to_scene(
            root=root, scene=scene, target_muscle_ids=impacted["MUSCLE"]
        )

    if is_full:
        register_blob_sync().sync_root_to_scene(root=root, scene=scene)
    elif impacted["BLOB"]:
        register_blob_sync().sync_root_to_scene(root=root, scene=scene, target_blob_ids=impacted["BLOB"])

    register_mirror_sync().sync_root_to_scene(root=root, scene=scene)


def _build_runtime_context(root, dirty_hints):
    delayed_changed_scps = _apply_delayed_queue(root)
    graph = RuntimeGraph()
    entity_sets = build_runtime_graph(root, graph)
    adjacency = graph.entity_adjacency()
    scc_idx, scc_sizes = _compute_scc_index(adjacency)
    dirty, is_full = _normalize_dirty_hints(root, dirty_hints)
    dirty["SCP"] |= delayed_changed_scps
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
    for et in ("SCP", "FIBER", "MUSCLE", "BLOB"):
        impacted_sets[et] |= extra[et]


def run_dependency_runtime(root, scene, dirty_hints=None, bake=False):
    delayed_changed_scps, graph, entity_sets, adjacency, scc_idx, scc_sizes, dirty, is_full = _build_runtime_context(
        root, dirty_hints
    )
    impacted_sets = _compute_impacted_sets(graph, dirty)
    changed_dest_scps = _apply_constraints(
        root=root,
        dirty=dirty,
        is_full=is_full,
        entity_sets=entity_sets,
        delayed_changed_scps=delayed_changed_scps,
        adjacency=adjacency,
        scc_idx=scc_idx,
        scc_sizes=scc_sizes,
    )
    _merge_constraint_impacts(graph, impacted_sets, changed_dest_scps)
    _run_visual_sync(root=root, scene=scene, is_full=is_full, impacted=impacted_sets, bake=bake)
