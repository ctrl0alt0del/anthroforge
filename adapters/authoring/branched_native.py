"""Publish compiled branched parts as one native Muscle and retained source surfaces."""
from ...app.use_cases.fiber_surface_create import _new_surface, _assign_refs
from ...app.use_cases.muscle_create import _new_muscle
from ...core.vcp.shared_point_storage import slots
from .volume import configure


def write(root, scene, name, output, previous):
    from .native import find
    system = root.af_vcp_system
    muscle = find(system.muscles, previous.get('muscle')) or _new_muscle(system, name, False, False)
    wrapper = find(system.fiber_surfaces, previous.get('surface')) or _new_surface(system, name, 'BRANCHED_LOFT', False, False)
    wrapper.branches.clear()
    parts, fibers = _write_parts(root, scene, output, previous)
    wrapper.construction_mode, wrapper.main_surface_id = 'BRANCHED_LOFT', parts['main']
    wrapper.flip_normals = output['native_properties']['flip_normals']
    wrapper.fiber_refs.clear(); _assign_refs(wrapper, list(fibers.values()))
    muscle.surface_source_mode, muscle.fiber_surface_id = 'FIBER_SURFACE', wrapper.id
    configure(muscle, output)
    for key, definition in output['branch_connections'].items():
        _connection(root, wrapper, muscle, key, definition, output, parts, fibers)
    return dict(muscle=muscle.id, surface=wrapper.id, fibers=fibers, parts=parts)


def _write_parts(root, scene, output, previous):
    from .native import find, write_fiber
    system, parts, fibers = root.af_vcp_system, {}, {}
    for key, part in output['branch_parts'].items():
        rows = [write_fiber(root, scene, row, find(system.fibers, previous.get('fibers', {}).get(row['id']))) for row in part['fibers']]
        fibers.update({row['id']: f.id for row, f in zip(part['fibers'], rows)})
        surface = find(system.fiber_surfaces, previous.get('parts', {}).get(key)) or _new_surface(system, key, 'LOFT', False, False)
        surface.fiber_refs.clear(); _assign_refs(surface, [f.id for f in rows])
        parts[key] = surface.id
    return parts, fibers


def _connection(root, wrapper, muscle, key, definition, output, parts, fibers):
    source = output['branch_parts']['main']['fibers'][0 if definition['boundary'] == 'first' else -1]
    main = next(f for f in root.af_vcp_system.fibers if f.id == fibers[source['id']])
    uses = slots(main)
    roots = [getattr(uses[i][0], uses[i][1]) for i in definition['root_anchor_indices']]
    connection = wrapper.branches.add()
    connection.id, connection.surface_id, connection.boundary_fiber_id = key, parts[key], main.id
    connection.width, connection.fullness = definition.get('width', .25), definition.get('fullness', 0.)
    connection.settings.id = muscle.id
    configure(connection.settings, output['branch_parts'][key])
    for point_id, row in zip(roots, output['branch_parts'][key]['fibers']):
        connection.roots.add().point_id = point_id
        child = next(f for f in root.af_vcp_system.fibers if f.id == fibers[row['id']])
        child.a_point_id = point_id


def junction_fibers(output):
    if 'branch_parts' not in output:
        return set()
    allowed = set()
    for key, definition in output['branch_connections'].items():
        parent = output['branch_parts']['main']['fibers'][0 if definition['boundary'] == 'first' else -1]
        children = output['branch_parts'][key]['fibers']
        for row, index in zip(children, definition['root_anchor_indices']):
            if row['anchors'][0] != parent['anchors'][index]:
                raise ValueError('Compiled junction anchor differs from its main point')
            allowed.add(row['id'])
    return allowed
