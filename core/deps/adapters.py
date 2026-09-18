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
)

try:
    from ..vcp.fiber_modes import fiber_parent_ids
    from ..vcp.fiber_node_attachment_codec import node_attachment_target_ids
    from ..vcp.surface_target import SurfaceTargetKind, effective_tissue_target, target_dependency
except ImportError:
    from core.vcp.fiber_modes import fiber_parent_ids
    from core.vcp.fiber_node_attachment_codec import node_attachment_target_ids
    from core.vcp.surface_target import SurfaceTargetKind, effective_tissue_target, target_dependency


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


def _add_fiber_entities(root, graph, entity_sets):
    if not hasattr(root, "af_vcp_system"):
        return
    for f in root.af_vcp_system.fibers:
        _add_one_fiber(root, graph, entity_sets, f)


def _add_one_fiber(root, graph, entity_sets, fiber):
    fid = fiber.id; entity_sets['FIBER'].add(fid)
    fp_in = graph.add_port(PortRef('FIBER', fid, 'input', PHASE_INPUT, MUT_INPUT))
    fp_local = graph.add_port(PortRef('FIBER', fid, 'local_eval', PHASE_LOCAL_EVAL, MUT_DERIVED))
    fp_att = graph.add_port(PortRef('FIBER', fid, 'attachment_world', PHASE_ATTACHMENT_WORLD, MUT_DERIVED))
    fp_probe = graph.add_port(PortRef('FIBER', fid, 'probe', PHASE_PROBES, MUT_PROBE))
    graph.add_edge(Edge(fp_in, fp_local, EDGE_EVAL))
    graph.add_edge(Edge(fp_local, fp_probe, EDGE_EVAL))
    graph.add_edge(Edge(fp_att, fp_probe, EDGE_EVAL))
    for sid in _fiber_attachment_ids(root, fiber):
        sp = graph.add_port(PortRef('SCP', sid, 'probe', PHASE_PROBES, MUT_PROBE))
        graph.add_edge(Edge(sp, fp_att, EDGE_ATTACHMENT))
        _add_dependency_edge(graph, ('SCP', sid), ('FIBER', fid))


def _fiber_attachment_ids(root, fiber):
    values = list(fiber_parent_ids(fiber))
    values.extend(node_attachment_target_ids(fiber))
    values = tuple(dict.fromkeys(str(v) for v in values if v))
    if not any(value.startswith('AFI_') for value in values):
        return values
    try: from ..scp_runtime.common import attachment_dependency_id
    except ImportError: from core.scp_runtime.common import attachment_dependency_id
    return tuple(dict.fromkeys(attachment_dependency_id(root, value) for value in values if value))


def _add_muscle_entities(root, graph, entity_sets):
    if not hasattr(root, "af_vcp_system"):
        return
    for muscle in root.af_vcp_system.muscles:
        _add_one_muscle(graph, entity_sets, muscle)


def _add_one_muscle(graph, entity_sets, muscle):
    entity_sets["MUSCLE"].add(muscle.id)
    source = graph.add_port(PortRef("MUSCLE", muscle.id, "input", PHASE_INPUT, MUT_INPUT))
    evaluated = graph.add_port(PortRef("MUSCLE", muscle.id, "local_eval", PHASE_LOCAL_EVAL, MUT_DERIVED))
    probe = graph.add_port(PortRef("MUSCLE", muscle.id, "probe", PHASE_PROBES, MUT_PROBE))
    graph.add_edge(Edge(source, evaluated, EDGE_EVAL))
    graph.add_edge(Edge(evaluated, probe, EDGE_EVAL))
    if not _add_muscle_surface_source(graph, muscle, evaluated):
        _add_legacy_muscle_edges(graph, muscle, evaluated)


def _add_legacy_muscle_edges(graph, muscle, target_port):
    for ref in muscle.fiber_refs:
        if not ref.fiber_id:
            continue
        probe = graph.add_port(PortRef("FIBER", ref.fiber_id, "probe", PHASE_PROBES, MUT_PROBE))
        graph.add_edge(Edge(probe, target_port, EDGE_EVAL))
        _add_dependency_edge(graph, ("FIBER", ref.fiber_id), ("MUSCLE", str(muscle.id)))


def _add_muscle_surface_source(graph, muscle, target_port):
    source_id = str(getattr(muscle, "fiber_surface_id", "") or "")
    if str(getattr(muscle, "surface_source_mode", "LEGACY_FIBERS")) != "FIBER_SURFACE" or not source_id:
        return False
    probe = graph.add_port(PortRef("FIBER_SURFACE", source_id, "probe", PHASE_PROBES, MUT_PROBE))
    graph.add_edge(Edge(probe, target_port, EDGE_EVAL))
    _add_dependency_edge(graph, ("FIBER_SURFACE", source_id), ("MUSCLE", str(muscle.id)))
    return True


def _add_fiber_surface_entities(root, graph, entity_sets):
    for surface in getattr(root.af_vcp_system, "fiber_surfaces", ()):
        sid = str(surface.id)
        entity_sets["FIBER_SURFACE"].add(sid)
        source = graph.add_port(PortRef("FIBER_SURFACE", sid, "input", PHASE_INPUT, MUT_INPUT))
        evaluated = graph.add_port(PortRef("FIBER_SURFACE", sid, "local_eval", PHASE_LOCAL_EVAL, MUT_DERIVED))
        probe = graph.add_port(PortRef("FIBER_SURFACE", sid, "probe", PHASE_PROBES, MUT_PROBE))
        graph.add_edge(Edge(source, evaluated, EDGE_EVAL))
        graph.add_edge(Edge(evaluated, probe, EDGE_EVAL))
        _add_surface_fiber_edges(graph, surface, evaluated)


def _add_surface_fiber_edges(graph, surface, target_port):
    _add_branch_surface_edges(graph, surface, target_port)
    for ref in surface.fiber_refs:
        if not ref.fiber_id:
            continue
        probe = graph.add_port(PortRef("FIBER", ref.fiber_id, "probe", PHASE_PROBES, MUT_PROBE))
        graph.add_edge(Edge(probe, target_port, EDGE_EVAL))
        _add_dependency_edge(graph, ("FIBER", ref.fiber_id), ("FIBER_SURFACE", str(surface.id)))


def _add_branch_surface_edges(graph, surface, target_port):
    if str(getattr(surface, "construction_mode", "")) != "BRANCHED_LOFT":
        return
    ids = (surface.main_surface_id, *(b.surface_id for b in surface.branches))
    for sid in ids:
        probe = graph.add_port(PortRef("FIBER_SURFACE", sid, "probe", PHASE_PROBES, MUT_PROBE))
        graph.add_edge(Edge(probe, target_port, EDGE_EVAL))
        _add_dependency_edge(graph, ("FIBER_SURFACE", sid), ("FIBER_SURFACE", str(surface.id)))


def _add_blob_entities(root, graph, entity_sets):
    if not hasattr(root, "af_vcp_system"):
        return
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


def _add_soft_tissue_entities(root, graph, entity_sets):
    if not hasattr(root, "af_vcp_system"):
        return
    for tissue in getattr(root.af_vcp_system, "soft_tissues", ()):
        tid = str(tissue.id)
        entity_sets["SOFT_TISSUE"].add(tid)
        source = graph.add_port(PortRef("SOFT_TISSUE", tid, "input", PHASE_INPUT, MUT_INPUT))
        evaluated = graph.add_port(PortRef("SOFT_TISSUE", tid, "local_eval", PHASE_LOCAL_EVAL, MUT_DERIVED))
        graph.add_edge(Edge(source, evaluated, EDGE_EVAL))
        _add_soft_tissue_dependency(graph, tissue, evaluated)


def _add_soft_tissue_dependency(graph, tissue, evaluated):
    source_type = str(getattr(tissue, "base_source_type", "OBJECT") or "OBJECT")
    source_id = str(getattr(tissue, "base_source_id", "") or "")
    if source_type in {"FIBER", "FIBER_SURFACE"} and source_id:
        probe = graph.add_port(PortRef(source_type, source_id, "probe", PHASE_PROBES, MUT_PROBE))
        graph.add_edge(Edge(probe, evaluated, EDGE_EVAL))
        _add_dependency_edge(graph, (source_type, source_id), ("SOFT_TISSUE", str(tissue.id)))
    _add_soft_tissue_target(graph, tissue, evaluated)


def _add_soft_tissue_target(graph, tissue, evaluated):
    target = effective_tissue_target(tissue)
    entity_type = target_dependency(target)
    if target.kind == SurfaceTargetKind.NONE or not entity_type:
        return
    probe = graph.add_port(PortRef(entity_type, target.entity_id, "probe", PHASE_PROBES, MUT_PROBE))
    graph.add_edge(Edge(probe, evaluated, EDGE_ATTACHMENT))
    _add_dependency_edge(graph, (entity_type, target.entity_id), ("SOFT_TISSUE", str(tissue.id)))


def build_runtime_graph(root, graph):
    entity_sets = {
        "SCP": set(),
        "FIBER": set(),
        "FIBER_SURFACE": set(),
        "MUSCLE": set(),
        "BLOB": set(),
        "SOFT_TISSUE": set(),
    }
    _add_scp_entities(root, graph, entity_sets)
    _add_fiber_entities(root, graph, entity_sets)
    _add_fiber_surface_entities(root, graph, entity_sets)
    _add_muscle_entities(root, graph, entity_sets)
    _add_blob_entities(root, graph, entity_sets)
    _add_soft_tissue_entities(root, graph, entity_sets)
    return entity_sets
