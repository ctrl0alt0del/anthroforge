"""One atomic commit path for Free creation, conversion, API and native editing."""
import copy
from mathutils import Vector
from ...core.vcp import free_path, fiber_authority
from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
from ...core.visualization import free_fiber_runtime as runtime
from ...adapters.free_fiber_transaction import run


def _check_edit(root, fiber, editing=False):
    if root.get('af_free_edit_' + fiber.id) and not editing:
        raise ValueError('EDIT_IN_PROGRESS: Apply or Cancel the open path editor first.')


def commit(root, scene, fiber, payload, points, expected_revision=None, editing=False):
    _check_edit(root, fiber, editing)
    if expected_revision is not None and fiber.free_path_revision != expected_revision:
        raise ValueError('STALE_PATH_REVISION')
    candidate = copy.deepcopy(payload)
    candidate['capture_revision'] = fiber.free_path_revision + 1
    raw, attachments = runtime.prepare(root, scene, fiber, candidate, points)
    from ...core.visualization.free_output_validation import validate_outputs
    validate_outputs(root, scene, {fiber.id: points}, {fiber.id: candidate})
    return run(root, scene, lambda: _commit(root, scene, fiber, raw, attachments, points))


def _commit(root, scene, fiber, raw, attachments, points):
    proxy = _store(root, scene, fiber, raw, attachments, points)
    rebuild(root, scene, {fiber.id})
    return proxy


def _store(root, scene, fiber, raw, attachments, points):
    from ...core.visualization.fiber_refinement import cancel_fiber_refinement
    from ...core.visualization.fiber_engine_migration import clear_engine_migration
    fiber_authority.invalidate(fiber); cancel_fiber_refinement(scene, fiber.id, False)
    clear_engine_migration(fiber)
    with suppress_vcp_prop_updates():
        fiber.behavior_mode = 'FREE'; fiber.free_path_json = raw
        fiber.node_attachments_json = attachments; fiber.free_path_revision += 1
        fiber['af_free_committed_mode'] = 'FREE'
        fiber.pop('af_controlled_retained_free', None)
    return runtime.publish(root, scene, fiber, points)


def rebuild(root, scene, ids):
    from ..runtime_api import sync_scene
    from ...core.deps.dirty_hints import dirty_hints_for
    sync_scene(root, scene, dirty_hints_for('FIBER', ids), source='free_path',
               event_type='FIBER_SOLVE_READY', payload={'solved_fiber_ids': sorted(ids)})
    from ...core.visualization.free_output_verification import verify_outputs
    verify_outputs(root, scene, ids)


def configure_mode(root, scene, fiber, mode):
    _check_edit(root, fiber)
    if mode not in {'FREE', 'CONTROLLED'}: raise ValueError('Invalid fiber behavior mode.')
    if fiber.behavior_mode == mode: return fiber
    if mode == 'FREE':
        from ...core.visualization.fiber_sync_helpers import persisted_fiber_points
        points = persisted_fiber_points(scene, root.name, fiber.id)
        if not points: raise ValueError('No valid committed path to freeze; conversion never starts a solve.')
        payload = payload_for_points(root, scene, fiber, points)
        commit(root, scene, fiber, payload, points)
    else: run(root, scene, lambda: _controlled(root, scene, fiber))
    return fiber


def _controlled(root, scene, fiber):
    from ...core.visualization.fiber_refinement import request_fiber_refinement
    fiber_authority.invalidate(fiber)
    fiber['af_controlled_retained_free'] = True
    with suppress_vcp_prop_updates(): fiber.behavior_mode = 'CONTROLLED'
    fiber['af_free_committed_mode'] = 'CONTROLLED'
    return request_fiber_refinement(root, scene, fiber, quality='FINAL')


def property_mode_changed(fiber, context):
    wanted = fiber.behavior_mode
    with suppress_vcp_prop_updates(): fiber.behavior_mode = fiber.get('af_free_committed_mode', 'CONTROLLED')
    try: configure_mode(fiber.id_data, context.scene, fiber, wanted)
    except (ValueError, RuntimeError) as error:
        from ...core.vcp.runtime_state import set_fiber_invalid_reason
        set_fiber_invalid_reason(fiber, str(error))


def payload_for_points(root, scene, fiber, points, indices=None):
    from ...core.vcp.shared_point_storage import migrate_root
    migrate_root(root)
    targets = runtime.anchor_points(root, scene, fiber)
    indices = exact_indices(points, targets, fiber.topology_mode) if indices is None else indices
    local = [root.matrix_world.inverted() @ Vector(p) for p in points]
    return free_path.make(local, fiber.topology_mode, runtime.structure(fiber), indices, fiber.free_path_revision)


def exact_indices(points, targets, topology):
    indices, cursor = [], 0
    for target in targets:
        found = [i for i in range(cursor, len(points)) if (Vector(points[i]) - target).length <= 1e-5]
        if len(found) != 1: raise ValueError('Missing or ambiguous exact structural sample; supply explicit tags.')
        indices.append(found[0]); cursor = found[0] + 1
    if topology == 'OPEN' and (indices[0] != 0 or indices[-1] != len(points) - 1):
        raise ValueError('Committed endpoints do not coincide with authored attachments.')
    return indices


def adjust_bound_points(root, scene, fiber, payload, points):
    from .free_point_edit import adjust
    adjust(root, scene, [f for f in root.af_vcp_system.fibers if free_path.is_free(f)])
    return True, '', runtime.publish(root, scene, fiber, runtime.current(root, scene, fiber)[1])
