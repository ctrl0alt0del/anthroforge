"""Prepare all persistent attachment data before publishing a routed curve."""
from ..vcp.attachment_surface import muscle_backed
from ..vcp.fiber_node_attachment import prepare_fiber_node_attachments
from ..vcp.prop_update_guard import suppress_vcp_prop_updates


def apply(sync, root, scene, fiber, points, bake, commit):
    if not commit or not muscle_backed(fiber):
        return sync.apply_points(root, scene, fiber, points, bake=bake, commit=commit)
    raw = prepare_fiber_node_attachments(root, scene, fiber, points, None)
    from ..vcp.fiber_support_validation import require_safe
    require_safe(root, scene, fiber, points)
    proxy = sync.apply_points(root, scene, fiber, points, bake=bake, commit=True)
    if proxy is None: raise ValueError('Fiber output could not be published.')
    with suppress_vcp_prop_updates(): fiber.node_attachments_json = raw
    from ..vcp.fiber_instance import MirroredFiber, retain_payload
    if isinstance(fiber, MirroredFiber): retain_payload(fiber.source, raw)
    fiber.pop('af_controlled_retained_free', None)
    return proxy
