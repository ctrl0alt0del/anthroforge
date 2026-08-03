try:
    from ...core.topology.model import TopologyDensityRule, TopologyOwnershipSource
except ImportError:
    from core.topology.model import TopologyDensityRule, TopologyOwnershipSource


def density_rules(root):
    return tuple(_density_rule(index, scp) for index, scp in enumerate(root.af_scp_system.scps))


def _density_rule(index, scp):
    return TopologyDensityRule(index, str(scp.id), str(scp.parent_id),
                               str(scp.topology_density_mode), int(scp.topology_subtree_quads))


def ownership_sources(root, scene, depsgraph):
    from ..draft_skin.capture import capture_skin
    sources = _captured_sources(capture_skin, root, scene, depsgraph)
    return tuple(_ownership_source(root, source) for source in sources)


def _captured_sources(capture_skin, root, scene, depsgraph):
    try:
        return capture_skin(root, scene, depsgraph).sources
    except ValueError:
        return ()


def _ownership_source(root, source):
    owners = source_owner_ids(root, source.entity_type, source.entity_id)
    return TopologyOwnershipSource(source.source_index, source.entity_type, source.entity_id,
                                   source.mirror_role, owners, source.vertices, source.triangles)


def source_owner_ids(root, entity_type, entity_id):
    if entity_type == "SCP":
        return (str(entity_id),)
    if entity_type == "FIBER":
        return _fiber_owner_ids(root, entity_id)
    if entity_type == "MUSCLE":
        return _muscle_owner_ids(root, entity_id)
    if entity_type == "BLOB":
        return _blob_owner_ids(root, entity_id)
    return ()


def _fiber_owner_ids(root, fiber_id):
    fiber = _by_id(root.af_vcp_system.fibers, fiber_id)
    if fiber is None:
        return ()
    values = [fiber.a_parent_id, fiber.b_parent_id]
    values.extend(item.parent_id for item in fiber.mid_touches)
    values.extend(item.parent_id for item in fiber.loop_anchors)
    return _unique(values)


def _muscle_owner_ids(root, muscle_id):
    muscle = _by_id(root.af_vcp_system.muscles, muscle_id)
    if muscle is None:
        return ()
    values = [_fiber_owner_ids(root, item.fiber_id) for item in muscle.fiber_refs]
    return _unique(value for group in values for value in group)


def _blob_owner_ids(root, blob_id):
    blob = _by_id(root.af_vcp_system.blobs, blob_id)
    if blob is None:
        return ()
    if blob.attach_target_type == "SCP":
        return _unique((blob.attach_target_id,))
    if blob.attach_target_type == "MUSCLE":
        return _muscle_owner_ids(root, blob.attach_target_id)
    return ()


def _by_id(items, entity_id):
    target = str(entity_id)
    return next((item for item in items if str(item.id) == target), None)


def _unique(values):
    return tuple(sorted({str(value) for value in values if str(value)}))
