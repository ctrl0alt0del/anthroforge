"""Strict material output-domain operations for the native authoring API."""
try:
    from tools.authoring_profile_schema import obj, _operation
except ModuleNotFoundError:
    from authoring_profile_schema import obj, _operation


def operations(defs):
    text = dict(type='string', minLength=1)
    xyz = dict(type='array', minItems=3, maxItems=3, items=dict(type='number'))
    plane = obj(dict(mode=dict(enum=['plane']), space=dict(enum=['root_local']), origin=xyz, normal=xyz,
                     keep_positive=dict(type='boolean')))
    defs['muscle_output_domain'] = dict(oneOf=[obj(dict(mode=dict(enum=['full']))), plane])
    fields = dict(muscle_id=text, configuration={'$ref': '#/$defs/muscle_output_domain'},
                  expected_scene_revision=text, expected_base_revision=text)
    return [_operation('domain_inspect', dict(muscle_id=text), ['muscle_id']),
            _operation('domain_configure', fields, list(fields))]
