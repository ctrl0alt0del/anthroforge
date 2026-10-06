"""Pair detection, layer evidence and stacking operations; details require an explicit revision."""
try:
    from tools.authoring_profile_schema import obj, _operation
except ModuleNotFoundError:
    from authoring_profile_schema import obj, _operation


def operations(defs):
    text = dict(type='string', minLength=1); distance = dict(type='number', minimum=0)
    groups = dict(type='object', additionalProperties=dict(type='string'))
    config = configuration(distance, groups)
    fields = dict(configuration=config, expected_scene_revision=text, expected_configuration_revision=text)
    fields.update(expected_relationship_revision=dict(type='integer', minimum=0), expected_result_revision=text)
    required = ['configuration', 'expected_scene_revision', 'expected_configuration_revision']
    footprint = dict(pair_index=dict(type='integer', minimum=0), relationship_id=text, expected_result_revision=text)
    return [_operation('pairs_inspect', {}, []), _operation('pairs_refresh', {}, []),
        _operation('pairs_footprint', footprint, ['expected_result_revision']), _operation('pairs_configure', fields, required),
        _operation('pairs_order_footprint', footprint, ['expected_result_revision']), _operation('stacking_inspect', {}, []),
        _operation('stacking_configure', fields, required), _operation('stacking_preview', dict(configuration=config), [])]


def configuration(distance, groups):
    key = dict(type='array', items=dict(type='string'), minItems=3, maxItems=3)
    pair = dict(type='array', items=key, minItems=2, maxItems=2)
    return obj(dict(automatic=dict(type='boolean'), search_distance=distance, displacement=distance, groups=groups,
        stacking=dict(type='boolean'), clearance=distance, smoothing_radius=distance, smoothing_strength=distance,
        exclusions=dict(type='array', items=pair), relationships=relationship_changes(key)), [])


def relationship_changes(key):
    face = dict(type='array', items=dict(type='integer', minimum=0), minItems=2, maxItems=2)
    region = dict(oneOf=[dict(enum=[None]), dict(type='array', items=face, minItems=1, maxItems=2000000)])
    return dict(type='array', items=obj(dict(id=dict(type='string', minLength=1), excluded=dict(type='boolean'),
        cover=dict(oneOf=[key, dict(enum=[None])]), region=region), ['id']))
