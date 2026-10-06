"""Package graph transfer with independent point IDs and remapped SCP/part ownership."""
from uuid import uuid4
from .rna import scalar_dict, apply_scalar_dict
from ..vcp.shared_point_storage import slots
from .free_fibers import remap_state


def capture_graph(root):
    system = root.af_vcp_system
    references = {f.id: [getattr(o, s) for o, s, _ in slots(f)] for f in system.fibers}
    surfaces = {s.id: dict(main=s.main_surface_id, branches=[_connection(c) for c in s.branches])
                for s in system.fiber_surfaces if s.construction_mode == 'BRANCHED_LOFT'}
    return dict(version=1, points=[scalar_dict(p) for p in system.authored_points], fibers=references, surfaces=surfaces)


def _connection(connection):
    return dict(props=scalar_dict(connection), roots=[r.point_id for r in connection.roots],
                settings=scalar_dict(connection.settings))


def restore_graph(state):
    data = getattr(state.snapshot, 'branching', {})
    if not data: return
    temporary = _temporary_points(state); point_ids = _restore_points(state, data)
    by_id = {f.id: f for f in state.root.af_vcp_system.fibers}
    for source, refs in data['fibers'].items():
        if source in state.fibers:
            fiber = by_id[state.fibers[source]]
            for (owner, slot, _), key in zip(slots(fiber), refs):
                setattr(owner, slot, point_ids[key])
    for source, graph in data['surfaces'].items():
        if source in state.fiber_surfaces:
            _restore_surface(state, source, graph, point_ids)
    _finish_graph(state, point_ids, temporary)


def _finish_graph(state, point_ids, temporary):
    from .free_correspondence import restore
    remap_state(state, point_ids)
    restore(state)
    _discard_temporary(state.root, temporary)


def _temporary_points(state):
    return {getattr(owner, slot) for f in state.root.af_vcp_system.fibers if f.id in state.fibers.values() for owner, slot, _ in slots(f)}


def _discard_temporary(root, keys):
    from ..vcp.shared_point_storage import referenced_point_ids, clear_indexes
    used = referenced_point_ids(root); points = root.af_vcp_system.authored_points
    for index in reversed(range(len(points))):
        if points[index].id in keys and points[index].id not in used: points.remove(index)
    clear_indexes()


def _restore_points(state, data):
    remap = getattr(state, 'scps', {})
    wanted = {key for f, refs in data['fibers'].items() if f in state.fibers for key in refs}
    mapping = {}
    for row in data['points']:
        if row['id'] not in wanted:
            continue
        point = state.root.af_vcp_system.authored_points.add()
        apply_scalar_dict(point, row)
        point.id = str(uuid4())
        point.parent_id = remap.get(point.parent_id, point.parent_id)
        mapping[row['id']] = point.id
    return mapping


def _restore_surface(state, source, graph, points):
    surface = next(s for s in state.root.af_vcp_system.fiber_surfaces if s.id == state.fiber_surfaces[source])
    surface.main_surface_id = state.fiber_surfaces[graph['main']]
    for record in graph['branches']:
        connection = surface.branches.add()
        apply_scalar_dict(connection, record['props'])
        connection.id = str(uuid4())
        connection.surface_id = state.fiber_surfaces[connection.surface_id]
        connection.boundary_fiber_id = state.fibers[connection.boundary_fiber_id]
        apply_scalar_dict(connection.settings, record['settings'])
        connection.settings.id = state.muscles[record['settings']['id']]
        for key in record['roots']:
            connection.roots.add().point_id = points[key]
