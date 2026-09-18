"""Closed protocol contracts for guided shared anatomy transfer."""
try:
    from tools.authoring_schema_v04 import S, I, B, ref, obj, array, operation
except ModuleNotFoundError:
    from authoring_schema_v04 import S, I, B, ref, obj, array, operation


def source_binding():
    return obj(dict(object=S, topology_digest=S, surface_binding=ref('surface_binding')))


def target_binding():
    return obj(dict(document_id=S, expected_draft_revision=I, region=ref('reference'),
                    topology_digest=S, surface_binding=ref('surface_binding')))


def settings():
    fields = dict(max_landmark_error=dict(type='number', exclusiveMinimum=0),
                  smoothing=dict(type='number', minimum=0, maximum=1), allow_reflection=B,
                  max_axis_ratio=dict(type='number', minimum=1),
                  samples_per_mesh=dict(type='integer', minimum=32, maximum=4096))
    return obj(fields, ['max_landmark_error'])


def operations():
    common = dict(expected_scene_revision=S, source_objects=array(S, 1, 128))
    rows = [operation('anatomy.transfer_sources', common, list(common))]
    pair = obj(dict(id=S, source=source_binding(), target=target_binding()))
    fields = dict(**common, correspondences=array(pair, 4, 256), settings=settings())
    required = list(fields)
    fields['annotations'] = array(obj(dict(id=S, label=S, source=source_binding())), 0, 1024)
    rows.append(operation('anatomy.transfer_preview', fields, required))
    publish = dict(expected_scene_revision=S, preview_id=S)
    return rows + [operation('anatomy.transfer_publish', publish, list(publish))]
