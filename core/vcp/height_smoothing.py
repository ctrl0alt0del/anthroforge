"""Immutable height-smoothing settings, shared by RNA and authoring."""
from dataclasses import dataclass, asdict
from math import isfinite, isclose

PREFIX = 'inflation_smoothing_'


@dataclass(frozen=True)
class HeightSmoothing:
    mode: str = 'OFF'
    radius: float = .2
    strength: float = .8
    max_change: float = .05


def normalize(value):
    if not isinstance(value, dict) or set(value) != {'mode', 'radius', 'strength', 'max_change'}:
        raise ValueError('SMOOTHING_CONFIGURATION_INVALID')
    if value['mode'] not in ('OFF', 'HEIGHT'):
        raise ValueError('SMOOTHING_MODE_UNSUPPORTED')
    for key in ('radius', 'strength', 'max_change'):
        number = value[key]
        if type(number) not in (int, float) or not isfinite(number) or not 0 <= number <= 1000:
            raise ValueError('SMOOTHING_PARAMETER_INVALID: '+key)
    return HeightSmoothing(**value)


def capture(settings):
    defaults = asdict(HeightSmoothing())
    return normalize({key: getattr(settings, PREFIX+key, default) for key, default in defaults.items()})


def properties(value=None):
    spec = HeightSmoothing() if value is None else normalize(value)
    return {PREFIX+key: item for key, item in asdict(spec).items()}


def wire(settings):
    spec = capture(settings)
    default = HeightSmoothing()
    unchanged = spec.mode == default.mode and all(isclose(getattr(spec, key), getattr(default, key), abs_tol=1e-7)
        for key in ('radius', 'strength', 'max_change'))
    return {} if unchanged else {'smoothing': asdict(spec)}


def active(spec):
    setting = spec.smoothing
    return spec.inflation_enabled and setting is not None and setting.mode == 'HEIGHT' and all(
        getattr(setting, key) > 0 for key in ('radius', 'strength', 'max_change'))
