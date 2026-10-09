"""Remap typed bindings only after both skeletal and volume IDs are allocated."""
from ..vcp.surface_reference import remap, remap_binding, reference, is_muscle
from ..vcp.fiber_node_attachment_codec import node_attachment_target_ids_from_raw, remap_node_attachment_targets


def capture(root):
    return {f.id: dict(supports=[row.target_id for row in f.attachment_supports], nodes=f.node_attachments_json,
        mirror_nodes=f.get('af_mirror_node_bindings', ''), mirror_source=f.get('af_mirror_binding_source', ''),
        symmetry={key: f[key] for key in f.keys() if key.startswith(('af_authoring_symmetry', 'af_authoring_mirror_'))})
        for f in root.af_vcp_system.fibers}


def restore(state, data):
    fibers = {f.id: f for f in state.root.af_vcp_system.fibers}
    scps, muscles = getattr(state, 'scps', {}), state.muscles
    for identity, row in data.get('surface_attachments', {}).items():
        if identity not in state.fibers: continue
        fiber = fibers[state.fibers[identity]]
        fiber.attachment_supports.clear()
        for value in row['supports']: fiber.attachment_supports.add().target_id = remap(value, scps, muscles)
        fiber.node_attachments_json = remap_nodes(row['nodes'], scps, muscles)
        for key, value in row.get('symmetry', {}).items(): fiber[key] = value
        _mirror(fiber, row, scps, muscles)


def remap_nodes(raw, scps, muscles):
    ids = node_attachment_target_ids_from_raw(raw)
    return remap_node_attachment_targets(raw, {value: remap(value, scps, muscles) for value in ids}) if raw else ''


def _mirror(fiber, row, scps, muscles):
    if not row.get('mirror_nodes'): return
    from ..vcp.fiber_instance import retain_payload
    retain_payload(fiber, remap_nodes(row['mirror_nodes'], scps, muscles))


def remap_point(point, scps, muscles):
    point.parent_id = remap(point.parent_id, scps, muscles)
    point.attach_param = remap_binding(point.attach_param, scps, muscles)


def available_targets(snapshot, available):
    from ..vcp.surface_reference import key
    values = set(available)
    for muscle in snapshot.muscles:
        for surface in ('MUSCLE_BASE', 'MUSCLE_INFL'):
            for instance in ('source', 'mirror'):
                values.add(key(dict(type='MUSCLE', id=muscle.source_id, surface=surface, instance=instance)))
    return values


def skeletal_ids(values):
    return {reference(value).entity_id for value in values if value and not is_muscle(value)}


def validate(snapshot):
    available = {m.source_id for m in snapshot.muscles}
    graph = getattr(snapshot, 'branching', {}); values = [p.get('parent_id', '') for p in graph.get('points', ())]
    for row in graph.get('surface_attachments', {}).values():
        values.extend(row.get('supports', ()))
        values.extend(node_attachment_target_ids_from_raw(row.get('nodes', '')))
    for fiber in snapshot.fibers:
        values.extend(fiber.props.get(key, '') for key in ('a_parent_id', 'b_parent_id'))
        values.extend(node_attachment_target_ids_from_raw(fiber.props.get('node_attachments_json', '')))
    missing = {reference(v).entity_id for v in values if is_muscle(v)} - available
    if missing: raise ValueError('Import is missing required muscle parents: ' + ', '.join(sorted(missing)))
    return any(is_muscle(v) for v in values)
