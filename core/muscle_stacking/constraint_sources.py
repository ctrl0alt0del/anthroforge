"""Read structural identities from authored Free samples or persisted controlled bindings."""
from ..vcp.free_path import decode, is_free, retained_free_geometry, tagged_indices
from ..vcp.shared_point_storage import slots, point_record


def structural(fiber, count):
    occurrences = slots(fiber)
    if is_free(fiber) or retained_free_geometry(fiber):
        payload = decode(fiber.free_path_json)
        if len(payload['samples']) != count: raise ValueError('STACK_ATTACHMENT_SAMPLES_STALE')
        indices = tagged_indices(payload)
        if [v['point_id'] for v in payload['structural']] != [getattr(o, s) for o, s, _ in occurrences]:
            raise ValueError('STACK_ATTACHMENT_IDENTITIES_STALE')
    else: indices = controlled_indices(fiber, count)
    if len(indices) != len(occurrences): raise ValueError('STACK_ATTACHMENT_CORRESPONDENCE_UNAVAILABLE')
    return tuple((i, str(getattr(owner, slot)), role) for i, (owner, slot, role) in zip(indices, occurrences)
        if protected(owner, slot))


def controlled_indices(fiber, count):
    from ..vcp.fiber_node_attachment_codec import decode_node_attachments
    from ..visualization.fiber_sync_runtime import _propagated_pin_indices
    payload = decode_node_attachments(fiber.node_attachments_json)
    indices = _propagated_pin_indices(fiber, payload)
    if payload is None or payload.point_count != count or indices is None:
        raise ValueError('STACK_CONTROLLED_ATTACHMENT_CORRESPONDENCE_UNAVAILABLE')
    return indices


def protected(owner, slot):
    point = point_record(owner, slot)
    if point is None: raise ValueError('STACK_ATTACHMENT_IDENTITY_MISSING')
    return bool(point.parent_id or point.stacking_fixed or point.protected_crease)
