"""Simplified underside and native Free loft, fitted as one stage."""
try:
    from tools.authoring_schema_v04 import S, I, N, obj, array, operation, ref
    from tools.authoring_partition_schema import repair, operations as partition_operations
except ModuleNotFoundError:
    from authoring_schema_v04 import S, I, N, obj, array, operation, ref
    from authoring_partition_schema import repair, operations as partition_operations


def pin():
    fields = dict(instance_id=S, position=ref('xyz'), max_distance=dict(type='number', minimum=0))
    required = list(fields)
    fields.update(mode=dict(enum=['fit', 'extend']), normal_offset=N, purpose=S)
    return obj(fields, required)


def patch():
    common = dict(id=S, head_ids=array(S, 1, 16), endpoints=array(obj(dict(start=pin(), end=pin())), 2, 8))
    required = list(common); common['output_domain'] = ref('muscle_output_domain')
    gridded = dict(common, grid_vertex_ids=array(array(I, 4, 129), 4, 129))
    selected = dict(common, source_triangles=array(I, 1, 8192), boundary_vertex_ids=array(I, 4, 4))
    return dict(oneOf=[obj(gridded, required+['grid_vertex_ids']), obj(selected, required+['source_triangles', 'boundary_vertex_ids'])])


def settings():
    number = lambda low, high: dict(type='number', minimum=low, maximum=high)
    fields = dict(longitudinal_controls=dict(type='integer', minimum=4, maximum=8), fairness=number(1e-8, 1),
                  junction_smoothness=number(0, 1), samples_per_fiber=dict(type='integer', minimum=9, maximum=65),
                  max_shape_error=dict(type='number', exclusiveMinimum=0), max_native_error=dict(type='number', exclusiveMinimum=0),
                  max_width_change=number(.01, 1), collision_radius=number(0, 1))
    return obj(fields, ['max_shape_error', 'max_native_error'])


def operations():
    side = obj(dict(patch_id=S, side=dict(enum=[0, 1])))
    seam = obj(dict(id=S, first=side, second=side))
    fields = dict(expected_scene_revision=S, source_object=S, topology_digest=S, geometry_digest=S,
                  family=S, heads=array(obj(dict(id=S, label=S)), 1, 16), patches=array(patch(), 1, 8),
                  seams=array(seam, 0, 8), settings=settings(), anatomical_note=S)
    required = list(fields); fields['overlap_repairs'] = array(repair(), 0, 4)
    rows = [operation('anatomy.smooth_base_preview', fields, required)]
    return rows+[operation('anatomy.smooth_base_publish', dict(expected_scene_revision=S, preview_id=S), ['expected_scene_revision', 'preview_id'])]+partition_operations()
