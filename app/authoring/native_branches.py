"""Revision-checked native branch and shared-point commands with replay and rollback."""
from ...core.authoring.codec import encode, decode, digest
from ...core.authoring.errors import require, AuthoringError
from ...core.authoring.reports import response
from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
from ...core.vcp.shared_point_storage import slots, point_users, ensure_point
from ..use_cases import muscle_branch as use

OPERATIONS = ('muscles.branch_inspect', 'muscles.branch_add', 'muscles.branch_remove',
              'muscles.branch_configure', 'points.inspect', 'points.edit', 'points.link', 'points.detach')
SETTINGS = ('inflation_enabled', 'inflation_mode', 'inflation_max_value', 'inflation_falloff_type',
            'inflation_falloff_radius', 'inflation_direction_depth', 'inflation_boundary_strength',
            'inflation_boundary_band', 'inflation_boundary_power', 'inflation_length_taper_band', 'inflation_ctrl_world')


def execute(port, request):
    from ...adapters.authoring.inventory import capture
    root, params = port.root, request['params']; require(params['scene_id'] == root.name, 'SCENE_NOT_FOUND')
    revision = capture(root, port.scene)['revision']
    if request['op'].endswith('inspect'):
        return dict(response(request, revision), entities=inspect(root, params))
    receipt = _receipt(root, request, revision)
    if receipt is not None:
        return receipt
    require(params['expected_scene_revision'] == revision, 'STALE_SCENE_REVISION')
    result = _transaction(root, request)
    revision = capture(root, port.scene)['revision']
    result = dict(response(request, revision), published=True, entities=[result])
    _remember(root, request, result)
    return result


def inspect(root, params):
    from ...adapters.authoring.records import record
    if 'muscle_id' in params:
        muscle = use.find_muscle(root, params['muscle_id'])
        return [dict(muscle=record(muscle), surface=record(use.muscle_surface(root, muscle)))]
    points = root.af_vcp_system.authored_points
    selected = [p for p in points if not params.get('point_id') or p.id == params['point_id']]
    return [dict(id=p.id, scp_id=p.parent_id, binding=p.attach_param, offset=p.normal_offset,
                 users=[dict(fiber_id=f.id, index=i, role=r) for f, i, r in point_users(root, p.id)]) for p in selected]


def _receipt(root, request, revision):
    saved = decode(root.get('af_branch_receipts', '{}')).get(request['request_id'])
    if saved is None:
        return None
    require(saved['digest'] == digest(request), 'REQUEST_ID_REUSED')
    require(saved['response']['scene_revision'] == revision, 'STALE_SCENE_REVISION')
    return dict(saved['response'], replayed=True)


def _remember(root, request, result):
    saved = decode(root.get('af_branch_receipts', '{}'))
    saved[request['request_id']] = dict(digest=digest(request), response=result)
    root['af_branch_receipts'] = encode(saved)


def _transaction(root, request):
    from ...adapters.authoring.capture import native_records
    saved = native_records(root)
    try:
        with suppress_vcp_prop_updates():
            result = _mutate(root, request['op'], request['params'])
    except Exception as error:
        _restore(root, saved)
        if isinstance(error, AuthoringError):
            raise
        raise AuthoringError('INVALID_BRANCH_CONFIGURATION', str(error)) from error
    _notify(root, request['op'], request['params'], result)
    return result


def _restore(root, saved):
    from ...adapters.authoring.records import restore
    with suppress_vcp_prop_updates():
        for name, records in saved.items():
            collection = getattr(root.af_vcp_system, name)
            collection.clear()
            for row in records:
                restore(collection.add(), row)


def _mutate(root, op, params):
    if op == 'muscles.branch_add':
        row = use.add_branch(root, params['muscle_id'], params['branch_surface_id'], params['boundary_fiber_id'], params['point_ids'])
        return dict(connection_id=row.id, muscle_id=params['muscle_id'])
    if op == 'muscles.branch_remove':
        use.remove_branch(root, params['muscle_id'], params['connection_id'])
        return dict(muscle_id=params['muscle_id'])
    if op == 'muscles.branch_configure':
        return _configure(root, params)
    return _point_mutation(root, op, params)


def _configure(root, params):
    surface = use.muscle_surface(root, use.find_muscle(root, params['muscle_id']))
    connection = next(c for c in surface.branches if c.id == params['connection_id'])
    for name, value in params.get('connector', {}).items():
        require(name in ('width', 'fullness'), 'INVALID_PARAMETER')
        setattr(connection, name, value)
    for name, value in params.get('inflation', {}).items():
        require(name in SETTINGS, 'INVALID_PARAMETER')
        setattr(connection.settings, name, value)
    if 'inflation_ctrl_world' in params.get('inflation', {}):
        connection.settings.inflation_ctrl_initialized = True
    return dict(connection_id=connection.id, muscle_id=params['muscle_id'])


def _point_mutation(root, op, params):
    if op == 'points.detach':
        return dict(point_id=use.detach_point(root, params['fiber_id'], params['index']))
    point = next(p for p in root.af_vcp_system.authored_points if p.id == params['point_id'])
    if op == 'points.link':
        _link(root, point, params)
    else:
        _edit(root, point, params)
    return dict(point_id=point.id)


def _link(root, point, params):
    key = params['fiber_id'], params['index']
    if key in use.protected_references(root):
        raise ValueError('Remove branch before replacing its root')
    fiber = next(f for f in root.af_vcp_system.fibers if f.id == key[0])
    owner, slot, role = slots(fiber)[key[1]]
    if role != 'MID' and point.normal_offset:
        raise ValueError('Use Add Branch to link an offset junction endpoint')
    if any(getattr(o, s) == point.id for o, s, _ in slots(fiber)):
        raise ValueError('A fiber cannot reference one point twice')
    setattr(owner, slot, point.id)


def _edit(root, point, params):
    import bpy
    from mathutils import Vector
    from ...core.vcp.fiber_pin_snapping import capture_attachment_from_world
    if 'position' in params:
        owner = params.get('scp_id', point.parent_id)
        radius = max((f.collision_radius for f, _, _ in point_users(root, point.id)), default=.002)
        raw = capture_attachment_from_world(root, bpy.context.scene, owner, Vector(params['position']),
                                            radius=radius, offset=params.get('offset', point.normal_offset))
        if raw is None:
            raise ValueError('Qualified surface snapping failed')
        point.parent_id, point.attach_param = owner, raw
    if 'offset' in params:
        _edit_offset(root, point, params['offset'])


def _edit_offset(root, point, offset):
    users = point_users(root, point.id)
    if offset and not any(role == 'MID' for _, _, role in users):
        raise ValueError('Ordinary endpoints must stay on the SCP surface')
    point.normal_offset = offset


def _notify(root, op, params, result):
    import bpy
    from ...core.vcp.shared_point_storage import point_updated
    if 'point_id' in result:
        point_updated(next(p for p in root.af_vcp_system.authored_points if p.id == result['point_id']), bpy.context)
    else:
        muscle = use.find_muscle(root, params['muscle_id'])
        surface = use.muscle_surface(root, muscle)
        branch = next((c for c in surface.branches if c.id == result.get('connection_id')), None)
        source = use.source_surface(root, branch.surface_id) if branch is not None else None
        fibers = {r.fiber_id for r in source.fiber_refs} if op == 'muscles.branch_add' and source else set()
        use._dirty(root, muscle, fibers)
