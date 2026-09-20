"""Legacy profile orientation follows the same source side as manual swapping."""
from dataclasses import replace
from ..authoring.legacy_config import legacy_state
from ..authoring.native_assignment import assign_checked
from ..vcp.prop_update_guard import suppress_vcp_prop_updates


def configuration_state(target):
    if target.muscle is None:
        return None
    state = legacy_state(target.muscle)
    if not state.pop('inflation_ctrl_initialized'):
        state.pop('inflation_ctrl_world')
    if target.assembly is not None:
        state.pop('flip_normals')
    mode = 'control_point' if target.muscle.inflation_mode == 'CTRL_POINT' else 'distributed'
    result = dict(mode=mode, native=state)
    if hasattr(target.source, 'flip_normals'):
        result['surface_flip_normals'] = bool(target.source.flip_normals)
    return result


def oriented_request(request, target, configuration):
    side = requested_side(target, configuration)
    if side is None:
        return request
    if target.assembly is not None:
        return replace(request, assembly=replace(request.assembly, flip=side))
    changes = dict(topology_flip_normals=side)
    if target.source == target.muscle:
        changes['flip_normals'] = side
    return replace(request, spec=replace(request.spec, **changes))


def requested_side(target, configuration):
    side = configuration.get('surface_flip_normals')
    native = configuration.get('native', {})
    if target.source == target.muscle and 'flip_normals' in native:
        if side is not None and side != native['flip_normals']:
            raise ValueError('PROFILE_SIDE_CONFLICT: legacy fiber source and inflation share one flip_normals property')
        side = native['flip_normals']
    return side


def publish_side(root, scene, target, configuration):
    if 'surface_flip_normals' not in configuration or target.source.flip_normals == configuration['surface_flip_normals']:
        return
    with suppress_vcp_prop_updates():
        assign_checked(target.source, 'flip_normals', configuration['surface_flip_normals'])
    from ...app.use_cases.muscle_tools import _sync_entity
    kind = 'MUSCLE' if target.source == target.muscle else 'FIBER_SURFACE'
    _sync_entity(root, scene, kind, {target.source.id})


def related_muscles(root, muscle):
    affected = related_entities(root, muscle)
    return tuple(item for item in root.af_vcp_system.muscles if ('MUSCLE', item.id) in affected)


def related_entities(root, muscle):
    if muscle is None:
        return set()
    from ..deps.adapters import build_runtime_graph
    from ..deps.runtime_graph import RuntimeGraph
    graph = RuntimeGraph()
    build_runtime_graph(root, graph)
    source = str(getattr(muscle, 'fiber_surface_id', ''))
    start = ('FIBER_SURFACE', source) if source and muscle.surface_source_mode == 'FIBER_SURFACE' else ('MUSCLE', muscle.id)
    return graph.downstream_entities({start}) | {('MUSCLE', muscle.id)}


def related_tissues(root, muscle):
    affected = related_entities(root, muscle)
    groups = (('BLOB', 'blobs'), ('SOFT_TISSUE', 'soft_tissues'))
    return tuple(item for kind, name in groups for item in getattr(root.af_vcp_system, name, ()) if (kind, item.id) in affected)


def normal_snapshot(root, muscle):
    if muscle is None:
        return None
    from ...app.use_cases.muscle_tools import _normal_target
    target, _ = _normal_target(root.af_vcp_system, muscle)
    return target, bool(target.flip_normals)
