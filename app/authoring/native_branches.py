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
                 stacking_fixed=p.stacking_fixed, protected_crease=p.protected_crease,
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
    saved = native_records(root); runtime = _runtime_memento(root)
    try:
        with suppress_vcp_prop_updates():
            result = _free_mutation(root, request)
        _notify(root, request['op'], request['params'], result)
    except Exception as error:
        _restore(root, saved); _restore_runtime(root, runtime)
        if isinstance(error, AuthoringError):
            raise
        raise AuthoringError('INVALID_BRANCH_CONFIGURATION', str(error)) from error
    return result


def _free_mutation(root, request):
    import bpy
    from ..use_cases.free_point_edit import graph_action
    if protection_only(request['op'], request['params']): return _mutate(root, request['op'], request['params'])
    return graph_action(root, bpy.context.scene, lambda: _mutate(root, request['op'], request['params']))


def protection_only(op, params):
    return op == 'points.edit' and bool({'stacking_fixed', 'protected_crease'} & params.keys()) and not bool({'position', 'attachment', 'offset', 'scp_id'} & params.keys())


def _restore(root, saved):
    from ...core.vcp.shared_point_storage import clear_indexes
    with suppress_vcp_prop_updates():
        for name, records in saved.items():
            _restore_collection(getattr(root.af_vcp_system, name), records)
    clear_indexes()


def _restore_collection(collection, records):
    from ...adapters.authoring.records import restore
    keys = {row['values']['id'] for row in records}
    for index in reversed(range(len(collection))):
        if collection[index].id not in keys:
            collection.remove(index)
    existing = {item.id: item for item in collection}
    for row in records:
        restore(existing.get(row['values']['id']) or collection.add(), row)


def _runtime_memento(root, scene=None):
    import bpy
    from ...core.vcp import fiber_anchor_preflight as preflight
    from ...core.visualization import fiber_anchor_overlay as overlay
    from ...core.warnings.session import REPOSITORY, scopes_for
    scene = scene or bpy.context.scene; names = ('fibers', 'fiber_surfaces', 'muscles'); scopes = set(scopes_for(scene, root))
    native = {name: {item.id: _custom_runtime(item) for item in getattr(root.af_vcp_system, name)} for name in names}
    proxies = {o.name: _custom_runtime(o, 'af_fiber_') for o in scene.objects if o.get('af_root_name') == root.name and o.get('af_fiber_id')}
    warnings = {key: dict(value) for key, value in REPOSITORY.provider_states.items() if key[0] in scopes}
    return dict(native=native, proxies=proxies, scopes=scopes, warnings=warnings,
                preflight=dict(preflight._CACHE), overlay=dict(overlay._BATCHES))


def _custom_runtime(item, prefix='_af_rt_'):
    from ...adapters.authoring.records import plain
    return {key: plain(item[key]) for key in item.keys() if key.startswith(prefix)}


def _restore_custom(item, saved, prefix='_af_rt_'):
    for key in tuple(item.keys()):
        if key.startswith(prefix) and key not in saved:
            del item[key]
    for key, value in saved.items():
        item[key] = value


def _restore_runtime(root, saved):
    import bpy
    from ...core.vcp import fiber_anchor_preflight as preflight
    from ...core.visualization import fiber_anchor_overlay as overlay
    for name, rows in saved['native'].items():
        for item in getattr(root.af_vcp_system, name):
            _restore_custom(item, rows.get(item.id, {}))
    for name, values in saved['proxies'].items():
        if bpy.data.objects.get(name) is not None:
            _restore_custom(bpy.data.objects[name], values, 'af_fiber_')
    _restore_warning_states(saved)
    preflight._CACHE.clear(); preflight._CACHE.update(saved['preflight'])
    overlay._BATCHES.clear(); overlay._BATCHES.update(saved['overlay'])


def _restore_warning_states(saved):
    from ...core.warnings.session import REPOSITORY
    for key in tuple(REPOSITORY.provider_states):
        if key[0] in saved['scopes']:
            del REPOSITORY.provider_states[key]
    for scope in saved['scopes']:
        REPOSITORY.states.pop(scope, None)
    for (scope, provider), value in saved['warnings'].items():
        REPOSITORY._state(scope, provider, value)
    REPOSITORY.changed()


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
    if params.get('inflation') and use.find_muscle(root, params['muscle_id']).envelope_sides == 'BOTH_SIDES':
        require(False, 'ENVELOPE_API_REQUIRED')
    surface = use.muscle_surface(root, use.find_muscle(root, params['muscle_id']))
    connection = next(c for c in surface.branches if c.id == params['connection_id'])
    for name, value in params.get('connector', {}).items():
        require(name in ('width', 'fullness'), 'INVALID_PARAMETER')
        setattr(connection, name, value)
    _configure_inflation(connection.settings, params.get('inflation', {}))
    return dict(connection_id=connection.id, muscle_id=params['muscle_id'])


def _configure_inflation(settings, values):
    mode = values.get('inflation_mode', settings.inflation_mode)
    require(mode != 'SECTION_PROFILE', 'PROFILE_DOMAIN_UNSUPPORTED')
    require(mode in ('CTRL_POINT', 'DISTRIBUTED'), 'PROFILE_MODE_UNSUPPORTED')
    for name, value in values.items():
        require(name in SETTINGS, 'INVALID_PARAMETER')
        setattr(settings, name, value)
    if 'inflation_ctrl_world' in values:
        settings.inflation_ctrl_initialized = True


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
    for key in ('stacking_fixed', 'protected_crease'):
        if key in params:
            require(type(params[key]) is bool, 'INVALID_PARAMETER'); setattr(point, key, params[key])
    if 'attachment' in params:
        _edit_retained(root, point, params)
    elif 'position' in params:
        _edit_position(root, point, params)
    if 'offset' in params:
        _edit_offset(root, point, params['offset'])


def _edit_position(root, point, params):
    import bpy
    from mathutils import Vector
    from ...core.vcp.fiber_pin_snapping import capture_attachment_from_world
    owner = params.get('scp_id', point.parent_id)
    radius = max((f.collision_radius for f, _, _ in point_users(root, point.id)), default=.002)
    raw = capture_attachment_from_world(root, bpy.context.scene, owner, Vector(params['position']),
                                        radius=radius, offset=params.get('offset', point.normal_offset))
    if raw is None:
        raise ValueError('Qualified surface snapping failed')
    point.parent_id, point.attach_param = owner, raw


def _edit_retained(root, point, params):
    import bpy
    from ...core.vcp.attachment_backend import attachment_runtime
    from ...core.vcp.fiber_pin_snapping import qualify_attachment
    require(not {'position', 'scp_id'} & params.keys(), 'INVALID_PARAMETER')
    binding = params['attachment']; owner, raw = binding['parent_id'], binding['attach_param']
    radius = max((f.collision_radius for f, _, _ in point_users(root, point.id)), default=.002)
    runtime = attachment_runtime(bpy.context.scene)
    _validate_retained_surface(root, bpy.context.scene, owner, raw, runtime)
    for offset in (0., params.get('offset', point.normal_offset)):
        result = qualify_attachment(root, bpy.context.scene, owner, raw, runtime, radius, offset)
        require(result.valid and result.raw == raw, 'RETAINED_ATTACHMENT_UNQUALIFIED',
                'Requested surface binding must remain exposed and unchanged at zero and final offsets.')
    point.parent_id, point.attach_param = owner, raw


def _validate_retained_surface(root, scene, owner, raw, runtime):
    from ...core.vcp.attachment_backend import _parent_mesh
    from ...core.scp_runtime.surface import build_mesh_surface_data
    values = _retained_values(raw); obj = _parent_mesh(root, scene, owner)
    require(obj is not None, 'RETAINED_ATTACHMENT_OWNER_NOT_FOUND')
    surface = build_mesh_surface_data(obj, runtime['depsgraph'], runtime['surface_cache'])
    triangles = () if surface is None else surface['triangles']
    ordered = {tuple(int(v) for v in tri) for tri in triangles}
    triangle = tuple(values['tri_vidx'])
    require(any(triangle[i:]+triangle[:i] in ordered for i in range(3)), 'RETAINED_ATTACHMENT_TRIANGLE_INVALID')


def _retained_values(raw):
    from math import isfinite
    data = decode(raw); require(isinstance(data, dict), 'RETAINED_ATTACHMENT_INVALID')
    require(data.get('mode') == 'surface_param_v2', 'RETAINED_ATTACHMENT_INVALID')
    triangle, weights = data.get('tri_vidx', ()), data.get('tri_weights', ())
    require(len(triangle) == len(weights) == 3, 'RETAINED_ATTACHMENT_INVALID')
    require(all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in triangle)
            and len(set(triangle)) == 3, 'RETAINED_ATTACHMENT_TRIANGLE_INVALID')
    require(all(isinstance(w, (int, float)) and not isinstance(w, bool) and isfinite(w) and 0 <= w <= 1 for w in weights),
            'RETAINED_ATTACHMENT_WEIGHTS_INVALID')
    require(abs(sum(weights)-1.) <= 1e-7, 'RETAINED_ATTACHMENT_WEIGHTS_INVALID')
    return data


def _edit_offset(root, point, offset):
    users = point_users(root, point.id)
    if offset:
        protected = use.protected_references(root)
        if not any(role == 'MID' for _, _, role in users) or any(role != 'MID' and (fiber.id, index) not in protected for fiber, index, role in users):
            raise ValueError('Ordinary endpoints must stay on the SCP surface')
    point.normal_offset = offset


def _notify(root, op, params, result):
    import bpy
    from ...core.vcp.shared_point_storage import point_updated, stacking_protection_updated
    if 'point_id' in result:
        notify = stacking_protection_updated if protection_only(op, params) else point_updated
        notify(next(p for p in root.af_vcp_system.authored_points if p.id == result['point_id']), bpy.context)
    else:
        muscle = use.find_muscle(root, params['muscle_id'])
        surface = use.muscle_surface(root, muscle)
        branch = next((c for c in surface.branches if c.id == result.get('connection_id')), None)
        source = use.source_surface(root, branch.surface_id) if branch is not None else None
        fibers = {r.fiber_id for r in source.fiber_refs} if op == 'muscles.branch_add' and source else set()
        use._dirty(root, muscle, fibers)
