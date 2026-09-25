"""Complete indexed footprint and source-cut contract for attachment grafting."""
try:
    from tools.authoring_schema_v04 import S, I, ref, obj, array, operation
except ModuleNotFoundError:
    from authoring_schema_v04 import S, I, ref, obj, array, operation


def operations():
    number = dict(type='number'); positive = dict(type='number', exclusiveMinimum=0)
    settings = obj(dict(cut_value=number, overlap_cut_value=number, escape_distance=positive, tolerance=positive,
                        departure_direction=ref('xyz'), attachment_axes=array(ref('xyz'), 2, 2), retained_axes=array(ref('xyz'), 2, 2),
                        validation_samples=dict(type='integer', minimum=64, maximum=60000)),
                   ['cut_value', 'overlap_cut_value', 'escape_distance', 'tolerance', 'departure_direction', 'attachment_axes', 'retained_axes'])
    face = obj(dict(tri_vidx=array(dict(type='integer', minimum=0), 3, 3), polygon=array(ref('xyz'), 3, 16)))
    common = dict(expected_scene_revision=S, source_object=S, topology_digest=S, geometry_digest=S, obstacle_instance_ids=array(S, 1, 16))
    fields = dict(**common, settings=settings, attachment_instance_id=S, source_cut_values=array(number, 4, 30000), footprint=array(face, 1, 30000))
    publish = dict(expected_scene_revision=S, preview_id=S)
    return [operation('anatomy.transfer_attachment_preview', fields, list(fields)), operation('anatomy.transfer_attachment_publish', publish, list(publish))]
