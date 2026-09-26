"""Validated and scaled secondary-side import without copied request receipts."""
from math import isfinite
from .muscle_profile import prepared_properties
from ..authoring.legacy_config import checked, FIELDS


def restore_secondary(owner, values, scale):
    from ..visualization.muscle_envelope_storage import restore
    if not isfinite(scale) or scale <= 0: raise ValueError('ENVELOPE_IMPORT_SCALE_INVALID')
    values = scaled_properties(values, scale)
    restore(owner, values)


def scaled_properties(values, scale):
    values = prepared_properties(values, scale)
    lengths = ('inflation_max_value', 'inflation_falloff_radius', 'inflation_direction_depth')
    for key in lengths:
        if key in values: values[key] = checked(key, values[key]*scale)
    if 'inflation_ctrl_world' in values:
        values['inflation_ctrl_world'] = checked('inflation_ctrl_world', [v*scale for v in values['inflation_ctrl_world']])
    for key in FIELDS & values.keys(): checked(key, values[key])
    return values
