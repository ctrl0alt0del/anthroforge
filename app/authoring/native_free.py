"""Guarded Free/Controlled creation and exact path editing with durable receipts."""
import copy
from mathutils import Vector
from ...core.authoring.codec import digest, decode, encode
from ...core.authoring.errors import require, AuthoringError
from ...core.authoring.reports import response
from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
from ...core.vcp import free_path, free_curve
from ...core.visualization import free_fiber_runtime as runtime
from ...adapters.authoring.inventory import capture
from ...adapters.free_fiber_transaction import run
from ..use_cases import free_fiber as service

OPERATIONS = ('fibers.create_controlled', 'fibers.create_free', 'fibers.path_inspect', 'fibers.path_update', 'fibers.mode_configure')


def execute(port, request, store):
    root, scene, params = port.root, port.scene, request['params']
    require(params['scene_id'] == root.name, 'SCENE_NOT_FOUND')
    revision = capture(root, scene)['revision']
    _request_identity(root, request, store)
    if request['op'] == 'fibers.path_inspect': return _response(request, root, scene, _fiber(root, params['fiber_id']))
    replayed = replay(root, scene, request)
    if replayed is not None: return replayed
    require(params['expected_scene_revision'] == revision, 'STALE_SCENE_REVISION')
    try: return run(root, scene, lambda: _execute_mutation(root, scene, request, store))
    except AuthoringError: raise
    except (ValueError, KeyError) as error: raise AuthoringError('INVALID_FREE_PATH', str(error)) from error


def _execute_mutation(root, scene, request, store):
    fiber = mutate(root, scene, request['op'], request['params'])
    result = _response(request, root, scene, fiber); result['published'] = True
    receipt = dict(digest=digest(request), response=result, fiber_id=fiber.id, postcondition=postcondition(root, scene, fiber))
    rows = decode(root.get('af_free_receipts', '{}')); rows[request['request_id']] = receipt
    key = [root.get('af_authoring_id') or root.name, request['request_id']]
    store.put('free_path_requests', key, dict(request=request, receipt=receipt))
    root['af_free_receipts'] = encode(rows); root['af_authoring_journal'] = str(store.directory)
    return result


def _request_identity(root, request, store):
    key = [root.get('af_authoring_id') or root.name, request['request_id']]
    for category in ('v04_requests', 'requests'):
        cached = store.get(category, key)
        require(not cached or cached.get('digest') == digest(request), 'REQUEST_ID_REUSED')
    for field in ('af_branch_receipts', 'af_free_receipts'):
        cached = decode(root.get(field, '{}')).get(request['request_id'])
        require(not cached or cached.get('digest') == digest(request), 'REQUEST_ID_REUSED')


def _fiber(root, identity):
    result = next((fiber for fiber in root.af_vcp_system.fibers if fiber.id == identity), None)
    require(result is not None, 'FIBER_NOT_FOUND')
    return result


def inspect(root, scene, fiber):
    points, error, payload = (), '', None
    if free_path.is_free(fiber):
        try: payload, points = runtime.current(root, scene, fiber)
        except ValueError as failure: error = str(failure)
    else:
        from ...core.visualization.fiber_sync_helpers import persisted_fiber_points
        points = persisted_fiber_points(scene, root.name, fiber.id) or ()
    return dict(fiber_id=fiber.id, behavior_mode=fiber.behavior_mode, path_revision=fiber.free_path_revision,
                path=payload, points_world=[list(p) for p in points], attachment_error=error,
                geometry_sample_count=len(points), controlled_node_count=fiber.node_count)


def _response(request, root, scene, fiber):
    return dict(response(request, capture(root, scene)['revision']), entities=[inspect(root, scene, fiber)])


def postcondition(root, scene, fiber):
    from ...adapters.authoring.records import record
    from ...core.utils import deformation_generation
    return digest(dict(record=record(fiber), points=inspect(root, scene, fiber)['points_world'],
                       root_matrix=[list(row) for row in root.matrix_world], generation=deformation_generation(scene)))


def replay(root, scene, request):
    saved = decode(root.get('af_free_receipts', '{}')).get(request['request_id'])
    if saved is None: return None
    require(saved['digest'] == digest(request), 'REQUEST_ID_REUSED')
    fiber = _fiber(root, saved['fiber_id'])
    require(saved['postcondition'] == postcondition(root, scene, fiber), 'STALE_FREE_PATH_RECEIPT')
    return dict(saved['response'], replayed=True)


def mutate(root, scene, op, params):
    if op.startswith('fibers.create_'): return create(root, scene, params, op.endswith('_free'))
    fiber = _fiber(root, params['fiber_id'])
    require(params['expected_path_revision'] == fiber.free_path_revision, 'STALE_PATH_REVISION')
    if op == 'fibers.mode_configure': return service.configure_mode(root, scene, fiber, params['mode'])
    require(free_path.is_free(fiber), 'FIBER_NOT_FREE')
    payload, points = _input(root, fiber, params['path'])
    _identities(fiber, payload)
    service.commit(root, scene, fiber, payload, points, params['expected_path_revision'])
    return fiber


def _identities(fiber, candidate):
    old = free_path.decode(fiber.free_path_json)['structural']
    require(candidate['structural'] == old, 'STRUCTURAL_IDENTITY_CHANGED')


def _input(root, fiber, value):
    payload = free_curve.input_payload(copy.deepcopy(value), fiber.topology_mode)
    points = [Vector(row['co']) for row in payload['samples']]
    if value['space'] == 'ROOT_LOCAL': points = [root.matrix_world @ point for point in points]
    return payload, points


def create(root, scene, params, free):
    from ...core.id_utils import next_prefixed_id
    with suppress_vcp_prop_updates():
        fiber = root.af_vcp_system.fibers.add(); fiber.id = next_prefixed_id(root.af_vcp_system.fibers, 'FIBER')
        fiber.behavior_mode = 'FREE' if free else 'CONTROLLED'; fiber.name = params.get('name', fiber.id)
        fiber.topology_mode = params.get('topology', 'OPEN'); _attachments(root, fiber, params['attachments'])
        _settings(fiber, params.get('settings', {}))
    if free:
        payload, points = _input(root, fiber, params['path']); service.commit(root, scene, fiber, payload, points)
    else:
        runtime.qualify(root, scene, fiber)
        from ...core.visualization.fiber_refinement import request_fiber_refinement
        request_fiber_refinement(root, scene, fiber, quality='FINAL')
    return fiber


def _settings(fiber, settings):
    allowed = ('node_count', 'solver_version', 'collision_radius', 'thickness', 'iterations_bake', 'use_surface_routing', 'use_segment_collisions')
    require(not set(settings) - set(allowed), 'INVALID_FIBER_SETTING')
    for key, value in settings.items(): setattr(fiber, key, value)


def _attachments(root, fiber, attachments):
    minimum = 3 if fiber.topology_mode == 'LOOP' else 2
    require(len(attachments) >= minimum, 'MANDATORY_ATTACHMENTS_MISSING')
    collection = fiber.loop_anchors if fiber.topology_mode == 'LOOP' else fiber.mid_touches
    for _ in range(len(attachments) - (0 if fiber.topology_mode == 'LOOP' else 2)): collection.add()
    from ...core.vcp.shared_point_storage import slots, clear_indexes
    for (owner, slot, _role), attachment in zip(slots(fiber), attachments):
        setattr(owner, slot, _attachment(root, attachment))
    clear_indexes()


def _attachment(root, attachment):
    identity = attachment['point_id']; points = root.af_vcp_system.authored_points
    point = next((row for row in points if row.id == identity), None)
    if point is not None:
        require(set(attachment) == {'point_id'}, 'SHARED_BINDING_IS_AUTHORITATIVE')
        return identity
    require(bool(attachment.get('parent_id') and attachment.get('attach_param')), 'MANDATORY_BINDING_MISSING')
    point = points.add(); point.id = identity; point.parent_id = attachment['parent_id']
    point.attach_param = attachment['attach_param']; point.normal_offset = attachment.get('normal_offset', 0.)
    return identity
