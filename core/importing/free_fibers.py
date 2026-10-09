"""Free graph validation and destination-frame remapping without a route solve."""
from mathutils import Vector
from ..vcp import free_path
from ..vcp.fiber_node_attachment_codec import node_attachment_target_ids_from_raw

_TRANSACTION = None


def set_transaction(callback):
    global _TRANSACTION
    _TRANSACTION = callback


def transaction(root, scene, action):
    if _TRANSACTION is None: raise RuntimeError('Free import transaction is not registered.')
    return _TRANSACTION(root, scene, action)


def validate_snapshot(snapshot, available):
    from .surface_attachments import available_targets
    available = available_targets(snapshot, available)
    graph = getattr(snapshot, 'branching', {})
    points = {p['id']: p for p in graph.get('points', ())}
    for fiber in snapshot.fibers:
        if fiber.props.get('behavior_mode') != 'FREE': continue
        payload = free_path.decode(fiber.props.get('free_path_json', ''))
        refs = graph.get('fibers', {}).get(fiber.source_id, ())
        if list(refs) != [r['point_id'] for r in payload['structural']]: raise ValueError('Free import is missing its exact shared point graph.')
        if any(key not in points for key in refs): raise ValueError('Free import is missing a shared point.')
        targets = set(node_attachment_target_ids_from_raw(fiber.props.get('node_attachments_json', '')))
        targets.update(points[key]['parent_id'] for key in refs)
        if targets - set(available): raise ValueError('Free import is missing required SCP references: ' + ', '.join(sorted(targets - set(available))))
        if payload.get('attachment_digest') != free_path.pair_digest(payload, fiber.props.get('node_attachments_json', '')): raise ValueError('Free import attachment pairing is invalid.')


def remap_fiber(root, scene, fiber, point_ids):
    from ..visualization import free_fiber_runtime as runtime
    if not free_path.is_free(fiber): return
    fiber.free_path_json = free_path.remap(fiber.free_path_json, point_ids, attachments=fiber.node_attachments_json)
    from ..vcp.attachment_surface import muscle_backed
    if muscle_backed(fiber): return _deferred_remap(fiber, runtime)
    payload, points = runtime.current(root, scene, fiber)
    inverse = root.matrix_world.inverted()
    for row, point in zip(payload['samples'], points): row['co'] = list(inverse @ Vector(point))
    payload['bindings'] = runtime.bindings(fiber)
    fiber.free_path_json = free_path.encode(payload)
    fiber['af_free_committed_mode'] = 'FREE'


def _deferred_remap(fiber, runtime):
    payload = free_path.decode(fiber.free_path_json)
    payload['bindings'] = runtime.bindings(fiber)
    payload['attachment_digest'] = free_path.pair_digest(payload, fiber.node_attachments_json)
    fiber.free_path_json = free_path.encode(payload); fiber['af_free_committed_mode'] = 'FREE'


def remap_state(state, point_ids):
    for fiber in state.root.af_vcp_system.fibers:
        if fiber.id in state.fibers.values(): remap_fiber(state.root, state.scene, fiber, point_ids)


def atomic_import(root, scene, snapshot, available, action):
    from .free_correspondence import validate
    validate(snapshot)
    validate_snapshot(snapshot, available)
    from .surface_attachments import validate as validate_surfaces
    muscles = validate_surfaces(snapshot)
    if not muscles and not getattr(snapshot, 'relationships', None) and not any(f.props.get('behavior_mode') == 'FREE' for f in snapshot.fibers): return action()
    return transaction(root, scene, lambda: _validated_import(root, action))


def _validated_import(root, action):
    result = action()
    from ..deps.surface_dependencies import require_acyclic
    require_acyclic(root)
    return result
