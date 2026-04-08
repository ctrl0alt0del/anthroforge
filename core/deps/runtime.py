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


def run_dependency_runtime(root, scene, dirty_hints=None, bake=False):
    # Phase 1: INPUT - consume delayed writes.
    delayed_changed_scps = _apply_delayed_queue(root)

    graph = RuntimeGraph()
    entity_sets = build_runtime_graph(root, graph)
    adjacency = graph.entity_adjacency()
    scc_idx, scc_sizes = _compute_scc_index(adjacency)

    dirty, is_full = _normalize_dirty_hints(root, dirty_hints)
    dirty["SCP"] |= delayed_changed_scps

    starts = set()
    for sid in dirty["SCP"]:
        starts.add(("SCP", sid))
    for fid in dirty["FIBER"]:
        starts.add(("FIBER", fid))
    for mid in dirty["MUSCLE"]:
        starts.add(("MUSCLE", mid))
    for bid in dirty["BLOB"]:
        starts.add(("BLOB", bid))

    impacted = graph.downstream_entities(starts) if starts else set()
    impacted |= starts

    impacted_scps = {eid for et, eid in impacted if et == "SCP"}
    impacted_fibers = {eid for et, eid in impacted if et == "FIBER"}
    impacted_muscles = {eid for et, eid in impacted if et == "MUSCLE"}
    impacted_blobs = {eid for et, eid in impacted if et == "BLOB"}

    # Phase 5: CONSTRAINT_APPLY
    changed_source_scps = set(dirty["SCP"])
    if is_full:
        changed_source_scps = set(entity_sets["SCP"])
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

    _DELAYED_WRITES.clear()
    _DELAYED_WRITES.update(new_delayed)

    if changed_dest_scps:
        impacted2 = graph.downstream_entities({("SCP", sid) for sid in changed_dest_scps})
        impacted2 |= {("SCP", sid) for sid in changed_dest_scps}
        impacted_scps |= {eid for et, eid in impacted2 if et == "SCP"}
        impacted_fibers |= {eid for et, eid in impacted2 if et == "FIBER"}
        impacted_muscles |= {eid for et, eid in impacted2 if et == "MUSCLE"}
        impacted_blobs |= {eid for et, eid in impacted2 if et == "BLOB"}

    # Phase 6: VIS_SYNC
    if is_full:
        register_sync().sync_root_to_scene(root=root, scene=scene)
    elif impacted_scps:
        register_sync().sync_root_to_scene(root=root, scene=scene, target_scp_ids=impacted_scps)

    if is_full:
        register_fiber_sync().sync_root_to_scene(root=root, scene=scene, bake=bake)
    elif impacted_fibers:
        register_fiber_sync().sync_root_to_scene(
            root=root, scene=scene, bake=bake, target_fiber_ids=impacted_fibers
        )

    if is_full:
        register_muscle_sync().sync_root_to_scene(root=root, scene=scene)
    elif impacted_muscles:
        register_muscle_sync().sync_root_to_scene(
            root=root, scene=scene, target_muscle_ids=impacted_muscles
        )

    if is_full:
        register_blob_sync().sync_root_to_scene(root=root, scene=scene)
    elif impacted_blobs:
        register_blob_sync().sync_root_to_scene(
            root=root, scene=scene, target_blob_ids=impacted_blobs
        )

    register_mirror_sync().sync_root_to_scene(root=root, scene=scene)
