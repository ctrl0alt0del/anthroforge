"""Strict partial configuration for the existing native inflation modes."""
from math import isfinite
from .errors import require

RANGES = dict(inflation_max_value=(0., 10.), inflation_falloff_radius=(.001, 100.),
    inflation_direction_depth=(.0001, 10.), inflation_boundary_strength=(0., 1.),
    inflation_boundary_band=(.1, 16.), inflation_boundary_power=(.1, 8.),
    inflation_length_taper_band=(.01, .49))
FIELDS = {*RANGES, 'inflation_enabled', 'inflation_falloff_type', 'inflation_ctrl_world', 'flip_normals'}
FALLOFFS = ('GAUSSIAN', 'LINEAR', 'SMOOTHSTEP')


def normalize_legacy(configuration):
    require(set(configuration) <= {'mode', 'native', 'surface_flip_normals'}, 'PROFILE_CONFIGURATION_INVALID')
    if set(configuration) == {'mode'}:
        return dict(configuration)
    values = configuration.get('native')
    require(isinstance(values, dict) and set(values) <= FIELDS, 'PROFILE_CONFIGURATION_INVALID')
    result = dict(mode=configuration['mode'], native={key: checked(key, value) for key, value in values.items()})
    if 'surface_flip_normals' in configuration:
        require(type(configuration['surface_flip_normals']) is bool, 'PROFILE_CONFIGURATION_INVALID')
        result['surface_flip_normals'] = configuration['surface_flip_normals']
    return result


def checked(key, value):
    if key in RANGES:
        low, high = RANGES[key]
        require(type(value) in (int, float) and isfinite(value) and low <= value <= high, 'PROFILE_PARAMETER_RANGE', key)
        return float(value)
    if key in ('inflation_enabled', 'flip_normals'):
        require(type(value) is bool, 'PROFILE_CONFIGURATION_INVALID', key)
    elif key == 'inflation_falloff_type':
        require(value in FALLOFFS, 'PROFILE_CONFIGURATION_INVALID', key)
    else:
        require(isinstance(value, (list, tuple)) and len(value) == 3, 'PROFILE_CONFIGURATION_INVALID', key)
        require(all(type(v) in (int, float) and isfinite(v) for v in value), 'PROFILE_PARAMETER_RANGE', key)
        return [float(v) for v in value]
    return value


def legacy_values(configuration, mode):
    values = dict(configuration.get('native', {}), inflation_mode=mode)
    if 'inflation_ctrl_world' in values:
        values['inflation_ctrl_initialized'] = True
    return values


def legacy_state(muscle):
    if muscle is None:
        return None
    result = {key: getattr(muscle, key) for key in sorted(FIELDS)}
    result['inflation_ctrl_world'] = list(result['inflation_ctrl_world'])
    result['inflation_ctrl_initialized'] = bool(muscle.inflation_ctrl_initialized)
    return {key: finite_wire(value) for key, value in result.items()}


def finite_wire(value):
    if isinstance(value, (list, tuple)):
        return [finite_wire(v) for v in value]
    return str(value) if isinstance(value, float) and not isfinite(value) else value
