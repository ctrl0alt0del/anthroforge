"""Strict versioned envelope wire configuration, shared by UI and authoring."""
from .errors import require
from .profile_config import native_values, wire
from .legacy_config import FIELDS, legacy_state
from ..vcp.muscle_section_profile import profile_from_muscle

SCHEMA = 'muscle_inflation_envelope.v1'


def normalize(value):
    require(isinstance(value, dict) and set(value) == {'schema', 'enabled', 'sides', 'reverse_sides', 'parts'}, 'ENVELOPE_CONFIGURATION_INVALID')
    require(value['schema'] == SCHEMA, 'ENVELOPE_VERSION_UNSUPPORTED')
    require(value['sides'] in ('one', 'both'), 'ENVELOPE_CONFIGURATION_INVALID')
    require(all(type(value[k]) is bool for k in ('enabled', 'reverse_sides')), 'ENVELOPE_CONFIGURATION_INVALID')
    require(isinstance(value['parts'], list) and bool(value['parts']), 'ENVELOPE_PART_MISMATCH')
    parts = [_part(part) for part in value['parts']]
    require(len({p['part_id'] for p in parts}) == len(parts), 'ENVELOPE_PART_MISMATCH')
    return dict(value, parts=parts)


def _part(value):
    require(isinstance(value, dict) and set(value) == {'part_id', 'a', 'b'}, 'ENVELOPE_PART_MISMATCH')
    require(isinstance(value['part_id'], str) and bool(value['part_id']), 'ENVELOPE_PART_MISMATCH')
    return dict(part_id=value['part_id'], a=_side(value['a']), b=_side(value['b']))


def _side(value):
    require(isinstance(value, dict) and set(value) == {'enabled', 'mode', 'parameters'}, 'ENVELOPE_SIDE_INVALID')
    require(type(value['enabled']) is bool and isinstance(value['parameters'], dict), 'ENVELOPE_SIDE_INVALID')
    parameters = value['parameters']
    if value['mode'] == 'section_profile':
        require(set(parameters) == {'profile_version', 'depths', 'peaks', 'roundness', 'direction'}, 'ENVELOPE_SIDE_INVALID')
    else:
        require(set(parameters) == (FIELDS - {'flip_normals', 'inflation_enabled', 'inflation_ctrl_world'}) | {'control'}, 'ENVELOPE_SIDE_INVALID')
        control = parameters['control']
        require(control == 'automatic' or isinstance(control, (list, tuple)), 'ENVELOPE_CONTROL_INVALID')
    native_values(side_configuration(value))
    return dict(value)


def side_configuration(value):
    if value['mode'] == 'section_profile':
        return dict(value['parameters'], mode=value['mode'], enabled=value['enabled'], flip_normals=False)
    params = dict(value['parameters']); control = params.pop('control')
    if control != 'automatic': params['inflation_ctrl_world'] = control
    return dict(mode=value['mode'], native=dict(params, inflation_enabled=value['enabled']))


def side_values(value):
    values = native_values(side_configuration(value)); values.pop('flip_normals', None)
    if value['mode'] != 'section_profile' and value['parameters']['control'] == 'automatic':
        values['inflation_ctrl_initialized'] = False
    return values


def side_state(settings):
    if settings.inflation_mode == 'SECTION_PROFILE':
        config = wire(profile_from_muscle(settings)); params = {k: v for k, v in config.items() if k not in ('enabled', 'flip_normals', 'mode')}
        return dict(enabled=bool(settings.inflation_enabled), mode='section_profile', parameters=params)
    params = legacy_state(settings); initialized = params.pop('inflation_ctrl_initialized')
    control = params.pop('inflation_ctrl_world'); params.pop('flip_normals'); params.pop('inflation_enabled')
    params['control'] = control if initialized else 'automatic'
    return dict(enabled=bool(settings.inflation_enabled), mode='control_point' if settings.inflation_mode == 'CTRL_POINT' else 'distributed', parameters=params)


def configuration(root, muscle):
    from ..visualization.muscle_envelope_storage import parts
    records = [dict(part_id=key, a=side_state(part), b=side_state(part.inflation_secondary if part.inflation_secondary.initialized else part))
               for key, part in parts(root, muscle)]
    return dict(schema=SCHEMA, enabled=muscle.envelope_enabled,
                sides='both' if muscle.envelope_sides == 'BOTH_SIDES' else 'one', reverse_sides=muscle.envelope_reverse, parts=records)
