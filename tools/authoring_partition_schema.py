"""Explicit adjacent strips, geometric limits, and opt-in construction hook."""
try:
    from tools.authoring_schema_v04 import S, N, obj, array, operation, ref
except ModuleNotFoundError:
    from authoring_schema_v04 import S, N, obj, array, operation, ref


def settings():
    positive = dict(type='number', exclusiveMinimum=0)
    return obj(dict(along_axis=ref('xyz'), across_axis=ref('xyz'), blend_distance=positive,
        max_displacement=positive, max_depth_gap=dict(type='number', minimum=0), max_outline_error=positive))


def repair():
    return obj(dict(patch_ids=array(S, 2, 2), sides=array(dict(enum=[0, 1]), 2, 2), settings=settings()))


def operations():
    paths = array(array(array(ref('xyz'), 2, 1025), 2, 8), 2, 2)
    fields = dict(expected_scene_revision=S, paths=paths, sides=array(dict(enum=[0, 1]), 2, 2), settings=settings())
    required = list(fields)
    fields['connection'] = obj(dict(main=dict(enum=[0, 1]), side=dict(enum=[0, 1]),
        root_indices=array(dict(type='integer', minimum=1), 2, 8)))
    return [operation('anatomy.partition_base_surfaces', fields, required)]
