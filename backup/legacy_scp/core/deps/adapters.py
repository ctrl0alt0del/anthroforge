from .types import (
    PortRef,
    Edge,
    PHASE_INPUT,
    PHASE_LOCAL_EVAL,
    PHASE_ATTACHMENT_WORLD,
    PHASE_PROBES,
    MUT_INPUT,
    MUT_DERIVED,
    MUT_PROBE,
    EDGE_EVAL,
    EDGE_ATTACHMENT,
    EDGE_CONSTRAINT_READ,
)

def _src_id_from_constraint(c):
    src_obj = getattr(c, "source_obj", None)
    if src_obj and src_obj.get("af_scp_id"):
        return str(src_obj.get("af_scp_id"))
    return str(getattr(c, "source_scp_id", "") or "")


def _add_dependency_edge(graph, src_entity, dst_entity):
    if src_entity == dst_entity:
        return
    graph.add_entity_edge(src_entity, dst_entity)


def _add_scp_entities(root, graph, entity_sets):
    for scp in root.af_scp_system.scps:
        sid = scp.id
        entity_sets["SCP"].add(sid)

        p_in = graph.add_port(PortRef("SCP", sid, "input", PHASE_INPUT, MUT_INPUT))
        p_local = graph.add_port(PortRef("SCP", sid, "local_eval", PHASE_LOCAL_EVAL, MUT_DERIVED))
        p_att = graph.add_port(PortRef("SCP", sid, "attachment_world", PHASE_ATTACHMENT_WORLD, MUT_DERIVED))
        p_probe = graph.add_port(PortRef("SCP", sid, "probe", PHASE_PROBES, MUT_PROBE))
        graph.add_edge(Edge(p_in, p_local, EDGE_EVAL))
        graph.add_edge(Edge(p_local, p_att, EDGE_EVAL))
        graph.add_edge(Edge(p_att, p_probe, EDGE_EVAL))

        if scp.parent_id:
            parent_probe = graph.add_port(PortRef("SCP", scp.parent_id, "probe", PHASE_PROBES, MUT_PROBE))
            graph.add_edge(Edge(parent_probe, p_att, EDGE_ATTACHMENT))
            _add_dependency_edge(graph, ("SCP", scp.parent_id), ("SCP", sid))

        for c in scp.constraints:
            if not bool(getattr(c, "enabled", True)):
                continue
            src_id = _src_id_from_constraint(c)
            if not src_id or src_id == sid:
                continue
            src_probe = graph.add_port(PortRef("SCP", src_id, "probe", PHASE_PROBES, MUT_PROBE))
            graph.add_edge(Edge(src_probe, p_in, EDGE_CONSTRAINT_READ))
            _add_dependency_edge(graph, ("SCP", src_id), ("SCP", sid))


def _add_fiber_entities(root, graph, entity_sets):
    for f in root.af_vcp_system.fibers:
        fid = f.id
        entity_sets["FIBER"].add(fid)
        fp_in = graph.add_port(PortRef("FIBER", fid, "input", PHASE_INPUT, MUT_INPUT))
        fp_local = graph.add_port(PortRef("FIBER", fid, "local_eval", PHASE_LOCAL_EVAL, MUT_DERIVED))
        fp_probe = graph.add_port(PortRef("FIBER", fid, "probe", PHASE_PROBES, MUT_PROBE))
        graph.add_edge(Edge(fp_in, fp_local, EDGE_EVAL))
        graph.add_edge(Edge(fp_local, fp_probe, EDGE_EVAL))

        parents = {sid for sid in (f.a_parent_id, f.b_parent_id) if sid}
        for tp in f.mid_touches:
            if tp.parent_id:
                parents.add(tp.parent_id)
        for sid in parents:
            sp = graph.add_port(PortRef("SCP", sid, "probe", PHASE_PROBES, MUT_PROBE))
            graph.add_edge(Edge(sp, fp_local, EDGE_ATTACHMENT))
            _add_dependency_edge(graph, ("SCP", sid), ("FIBER", fid))


def _add_muscle_entities(root, graph, entity_sets):
    for m in root.af_vcp_system.muscles:
        mid = m.id
        entity_sets["MUSCLE"].add(mid)
        mp_in = graph.add_port(PortRef("MUSCLE", mid, "input", PHASE_INPUT, MUT_INPUT))
        mp_local = graph.add_port(PortRef("MUSCLE", mid, "local_eval", PHASE_LOCAL_EVAL, MUT_DERIVED))
        mp_probe = graph.add_port(PortRef("MUSCLE", mid, "probe", PHASE_PROBES, MUT_PROBE))
        graph.add_edge(Edge(mp_in, mp_local, EDGE_EVAL))
        graph.add_edge(Edge(mp_local, mp_probe, EDGE_EVAL))

        for ref in m.fiber_refs:
            if not ref.fiber_id:
                continue
            fp = graph.add_port(PortRef("FIBER", ref.fiber_id, "probe", PHASE_PROBES, MUT_PROBE))
            graph.add_edge(Edge(fp, mp_local, EDGE_EVAL))
            _add_dependency_edge(graph, ("FIBER", ref.fiber_id), ("MUSCLE", mid))


def _add_blob_entities(root, graph, entity_sets):
    for b in root.af_vcp_system.blobs:
        bid = b.id
        entity_sets["BLOB"].add(bid)
        bp_in = graph.add_port(PortRef("BLOB", bid, "input", PHASE_INPUT, MUT_INPUT))
        bp_local = graph.add_port(PortRef("BLOB", bid, "local_eval", PHASE_LOCAL_EVAL, MUT_DERIVED))
        graph.add_edge(Edge(bp_in, bp_local, EDGE_EVAL))

        if b.attach_target_type == "SCP" and b.attach_target_id:
            sp = graph.add_port(PortRef("SCP", b.attach_target_id, "probe", PHASE_PROBES, MUT_PROBE))
            graph.add_edge(Edge(sp, bp_local, EDGE_ATTACHMENT))
            _add_dependency_edge(graph, ("SCP", b.attach_target_id), ("BLOB", bid))
        elif b.attach_target_type == "MUSCLE" and b.attach_target_id:
            mp = graph.add_port(PortRef("MUSCLE", b.attach_target_id, "probe", PHASE_PROBES, MUT_PROBE))
            graph.add_edge(Edge(mp, bp_local, EDGE_ATTACHMENT))
            _add_dependency_edge(graph, ("MUSCLE", b.attach_target_id), ("BLOB", bid))


def build_runtime_graph(root, graph):
    entity_sets = {
        "SCP": set(),
        "FIBER": set(),
        "MUSCLE": set(),
        "BLOB": set(),
    }
    _add_scp_entities(root, graph, entity_sets)
    _add_fiber_entities(root, graph, entity_sets)
    _add_muscle_entities(root, graph, entity_sets)
    _add_blob_entities(root, graph, entity_sets)
    return entity_sets
