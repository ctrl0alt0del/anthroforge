"""Closed guided whole-underside and SCP-bound native reconstruction vocabulary."""
try:
    from tools.authoring_schema_v04 import S, I, N, obj, array, operation, ref, enum
except ModuleNotFoundError:
    from authoring_schema_v04 import S, I, N, obj, array, operation, ref, enum


def define_operation():
    patch = obj(dict(id=S, head_ids=array(S, 1, 32), source_triangles=array(I, 1, 8192), boundary_vertex_ids=array(I, 4, 4)))
    fields = dict(expected_scene_revision=S, source_object=S, topology_digest=S, geometry_digest=S,
                  prepared_base_id=S, heads=array(obj(dict(id=S, label=S)), 1, 32), patches=array(patch, 1, 16), anatomical_note=S)
    result = operation('anatomy.define_base', fields, ['expected_scene_revision', 'heads', 'patches', 'anatomical_note'])
    common = {k: fields[k] for k in ('expected_scene_revision', 'heads', 'patches', 'anatomical_note')}
    direct = dict(common, scene_id=S, **{k: fields[k] for k in ('source_object', 'topology_digest', 'geometry_digest')})
    result['properties']['params'] = dict(oneOf=[obj(direct), obj(dict(common, scene_id=S, prepared_base_id=S))])
    return result


def binding():
    interval = array(dict(type='number', minimum=0, maximum=1), 2, 2)
    fields = dict(role=enum('origin', 'insertion', 'route'), document_id=S, expected_draft_revision=I,
                  region=ref('reference'), across=interval, max_distance=dict(type='number', minimum=0))
    required = list(fields)
    fields.update(along=interval, facing=ref('xyz'), minimum_facing_dot=dict(type='number', minimum=-1, maximum=1))
    return obj(fields, required)


def plan_operation():
    fields = dict(expected_scene_revision=S, base_id=S, tolerance=dict(type='number', exclusiveMinimum=0),
                  parts=array(obj(dict(patch_id=S, bindings=array(binding(), 2, 64))), 1, 16))
    required = list(fields)
    fields.update(max_middle_points=dict(type='integer', minimum=0, maximum=8), collision_radius=dict(type='number', minimum=0),
                  max_fibers=dict(type='integer', minimum=2, maximum=33), candidate_count=dict(type='integer', minimum=3, maximum=33),
                  samples_per_fiber=dict(type='integer', minimum=5, maximum=129),
                  max_solver_calls=dict(type='integer', minimum=1, maximum=256), solver_budget_ms=dict(type='integer', minimum=1, maximum=10000))
    return operation('anatomy.plan_base_fibers', fields, required)


def operations():
    try:
        from tools.authoring_smooth_schema import operations as smooth_operations
    except ModuleNotFoundError:
        from authoring_smooth_schema import operations as smooth_operations
    fields = dict(expected_scene_revision=S, plan_id=S)
    return [define_operation(), plan_operation(), operation('anatomy.publish_base_fibers', fields, list(fields))]+preparation_operations()+smooth_operations()


def preparation_operations():
    source = dict(source_object=S, topology_digest=S, geometry_digest=S)
    fields = dict(expected_scene_revision=S, support_instances=array(S, 1, 128), **source)
    result = [operation('anatomy.base_candidates', fields, list(fields))]
    fields = dict(expected_scene_revision=S, sources=array(obj(source), 1, 32))
    return result+[operation('anatomy.repair_volume', fields, list(fields))]
