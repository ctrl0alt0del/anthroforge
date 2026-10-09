"""Resolve and publish authoritative Free geometry without a routing engine."""
from mathutils import Vector
from ..vcp import free_path
from ..vcp.attachment_backend import attachment_runtime
from ..vcp.fiber_node_attachment import (_anchor_specs, prepare_fiber_node_attachments,
                                         resolve_fiber_node_attachments)
from ..vcp.shared_point_storage import slots, point_record
from ..vcp.runtime_state import set_fiber_invalid_reason, set_fiber_recompute_status
from .fiber_sync import register_fiber_sync
from .fiber_sync_helpers import mark_fiber_output_stale


def structure(fiber):
    return tuple((str(getattr(owner, slot)), role) for owner, slot, role in slots(fiber))


def bindings(fiber):
    records = [point_record(owner, slot) for owner, slot, _role in slots(fiber)]
    if any(row is None for row in records): raise ValueError('Missing shared attachment identity.')
    return [dict(parent_id=p.parent_id, attach_param=p.attach_param, normal_offset=p.normal_offset) for p in records]


def validate_structure(fiber, payload):
    free_path.validate(payload)
    if payload['topology'] != fiber.topology_mode: raise ValueError('Free path topology changed.')
    tagged = tuple((row['point_id'], row['role']) for row in payload['structural'])
    if tagged != structure(fiber): raise ValueError('Structural points cannot be detached, reordered or duplicated by path editing.')


def anchor_points(root, scene, fiber, runtime=None):
    values = _anchor_specs(root, scene, fiber, runtime or attachment_runtime(scene))
    if len(values) != len(slots(fiber)): raise ValueError('Mandatory attachment does not resolve.')
    return tuple(row[2] for row in values)


def qualify(root, scene, fiber):
    from ..vcp.fiber_pin_snapping import qualify_attachment
    from ..vcp.attachment_surface import support_keys
    runtime = attachment_runtime(scene)
    runtime['supports'] = support_keys(fiber)
    for row in bindings(fiber):
        result = qualify_attachment(root, scene, row['parent_id'], row['attach_param'], runtime,
                                    fiber.collision_radius, row['normal_offset'])
        if not result.valid or result.raw != row['attach_param']:
            raise ValueError('INVALID_ATTACHMENT: ' + (result.reason or 'Qualification changed the retained binding.'))


def prepare(root, scene, fiber, payload, points):
    validate_structure(fiber, payload); free_path.coordinates(points, fiber.topology_mode)
    indices = free_path.tagged_indices(payload); targets = anchor_points(root, scene, fiber)
    if any((Vector(points[i]) - target).length > 1e-5 for i, target in zip(indices, targets)):
        raise ValueError('Structural sample must coincide with its exact bound point.')
    qualify(root, scene, fiber)
    raw = prepare_fiber_node_attachments(root, scene, fiber, points, indices)
    inverse = root.matrix_world.inverted()
    for row, point in zip(payload['samples'], points): row['co'] = list(inverse @ Vector(point))
    payload['bindings'] = bindings(fiber); payload['attachment_digest'] = free_path.pair_digest(payload, raw)
    return free_path.encode(payload), raw


def current(root, scene, fiber, runtime=None):
    payload = validate_pair(fiber)
    result = resolve_fiber_node_attachments(root, scene, fiber, runtime)
    if not result.ok: raise ValueError(result.error)
    free_path.coordinates(result.points, fiber.topology_mode)
    return payload, result.points


def validate_pair(fiber):
    payload = free_path.decode(fiber.free_path_json); validate_structure(fiber, payload)
    if payload.get('attachment_digest') != free_path.pair_digest(payload, fiber.node_attachments_json):
        raise ValueError('Free path attachment/sample pairing is invalid.')
    return payload


def update(root, scene, fiber, runtime=None):
    try:
        payload, points = current(root, scene, fiber, runtime)
        if payload.get('bindings') != bindings(fiber):
            from ...app.use_cases.free_fiber import adjust_bound_points
            return adjust_bound_points(root, scene, fiber, payload, points)
        return True, '', publish(root, scene, fiber, points)
    except (ValueError, RuntimeError) as error:
        set_fiber_invalid_reason(fiber, str(error)); set_fiber_recompute_status(fiber, 'INVALID_ATTACHMENT')
        mark_fiber_output_stale(scene, root.name, fiber.id)
        return False, str(error), None


def publish(root, scene, fiber, points, validated=False):
    from ..vcp.fiber_support_validation import require_safe
    if not validated: require_safe(root, scene, fiber, points)
    proxy = register_fiber_sync().apply_points(root, scene, fiber, tuple(Vector(p) for p in points), commit=True)
    if proxy is None: raise ValueError('Free curve proxy is unavailable.')
    proxy.pop('af_fiber_display_mode', None); proxy['af_fiber_behavior_mode'] = 'FREE'
    for key in tuple(proxy.keys()):
        if key.startswith(('af_fiber_output_engine', 'af_fiber_requested_engine')): del proxy[key]
    set_fiber_invalid_reason(fiber, ''); set_fiber_recompute_status(fiber, 'FREE_UPDATED')
    return proxy
