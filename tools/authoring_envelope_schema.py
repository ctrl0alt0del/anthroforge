"""Versioned envelope operations, sharing the portable native configuration."""
try: from tools.authoring_profile_schema import obj, _operation
except ModuleNotFoundError: from authoring_profile_schema import obj, _operation


def operations(defs):
    text = dict(type='string', minLength=1)
    config = {'$ref': '#/$defs/native_muscle_envelope'}
    target = obj(dict(muscle_id=text))
    guards = dict(expected_scene_revision=text, expected_base_revision=text, expected_configuration_revision=text)
    preview = dict(target=target, configuration=config, include_geometry=dict(type='boolean'), **guards)
    configure = dict(muscle_id=text, configuration=config, **guards)
    return [_operation('inflation_inspect', dict(target=target), ['target']),
        _operation('inflation_preview', preview, ['target', 'configuration', *guards]),
        _operation('inflation_configure', configure, list(configure))]
