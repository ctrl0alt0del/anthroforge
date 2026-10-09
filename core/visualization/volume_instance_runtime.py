"""Independent native volume evaluation from the actual mirrored Fiber rows."""
from mathutils import Matrix
from .geometry_instance import required, mirrored
from .mirror_objects import ensure_private_data, create_mirror_from_source
from .muscle_sync_helpers import update_mesh


def surface_mirror(root, scene, surface, source):
    if not required(root, surface): return _remove_surface_mirror(root, scene, surface.id)
    from .mirror_rules import effective_rule_for_muscle
    from .fiber_surface_sync import evaluate_surface_record
    rule = effective_rule_for_muscle(surface, {f.id: f for f in root.af_vcp_system.fibers}, {s.id: s for s in root.af_scp_system.scps})
    if rule is None: return _remove_surface_mirror(root, scene, surface.id)
    target = _ensure(root, scene, source, 'fiber_surface', surface.id)
    try:
        with mirrored(rule): result = evaluate_surface_record(root, scene, surface)
        _publish(target, result.vertices, result.faces, 'fiber_surface')
    except (ValueError, RuntimeError) as error: _failed(target, 'fiber_surface', error)


def _remove_surface_mirror(root, scene, identity):
    from .mirror_objects import remove_obj
    for obj in tuple(scene.objects):
        if obj.get('af_root_name') == root.name and obj.get('af_fiber_surface_mirror_proxy') and obj.get('af_source_fiber_surface_id') == identity:
            remove_obj(obj)


def _ensure(root, scene, source, kind, identity):
    target = next((o for o in scene.objects if o.get('af_root_name') == root.name
        and o.get('af_' + kind + '_mirror_proxy') and o.get('af_source_' + kind + '_id') == identity), None)
    if target is None: target = create_mirror_from_source(source.users_collection[0], source, source.name + '_MIRROR')
    target['af_root_name'] = root.name; target['af_' + kind + '_proxy'] = True
    target['af_' + kind + '_id'] = identity
    target['af_' + kind + '_mirror_proxy'] = True
    target['af_source_' + kind + '_id'] = identity
    return target


def _publish(target, vertices, faces, kind):
    ensure_private_data(target); target.matrix_world = Matrix.Identity(4)
    update_mesh(target, vertices, faces)
    target['af_' + kind + '_output_state'] = 'CURRENT'
    target['af_independent_surface_instance'] = True
    target.pop('af_attachment_error', None)


def _failed(target, kind, error):
    target['af_' + kind + '_output_state'] = 'STALE'
    target['af_attachment_error'] = str(error)


def muscle_mirror(root, scene, muscle, target, role, rule):
    if not required(root, muscle): return False
    try:
        result = _muscle_result(root, scene, muscle, rule)
        from ..vcp.muscle_envelope import faces_for
        points = result.base_vertices if role == 'BASE' else result.inflated_vertices
        _publish(target, points, faces_for(result, role == 'INFL'), 'muscle')
    except (ValueError, RuntimeError) as error: _failed(target, 'muscle', error)
    return True


def _muscle_result(root, scene, muscle, rule):
    from .muscle_sync import register_muscle_sync
    from .muscle_numeric_runtime import _numeric_input, _make_request, _safe_branched_request
    from ..vcp.muscle_numeric import execute_muscle_batch
    from ..muscle_pairs.capture import remember_mirror
    with mirrored(rule):
        request = _safe_branched_request(root, scene, muscle)
        if request is None: request = _make_request(muscle, _numeric_input(register_muscle_sync(), root, scene, muscle))
        result = execute_muscle_batch((request,), 'NATIVE').results[0]
    if result.error: raise ValueError(result.error)
    remember_mirror(root, muscle.id, request, result)
    return result


def tissue_mirror(root, scene, tissue, target, rule):
    if tissue.constraint_reference != 'SOURCE': return False
    try:
        from .soft_tissue_sync import _evaluate_generic_tissue, register_soft_tissue_sync
        with mirrored(rule): result = _evaluate_generic_tissue(register_soft_tissue_sync(), root, scene, tissue, 'NONE')
        _publish(target, result.final.vertices, result.rest.faces, 'soft_tissue')
    except (ValueError, RuntimeError) as error: _failed(target, 'soft_tissue', error)
    return True
