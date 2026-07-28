from dataclasses import asdict

from .constants import (
    AUTO_ZERO_TERMS,
    BLEND_RADIUS_RATIO,
    PADDING_SAFETY_RATIO,
    REQUIRED_PROBE_RATIO,
    REST_PROBE_RATIO,
)
from .model import SkinSolverSettings


DEFAULT_SETTINGS = SkinSolverSettings()


def settings_from_percentages(minimum, depth, core, falloff):
    values = (minimum, depth, core, falloff)
    return SkinSolverSettings(*(float(value) / 100.0 for value in values))


def settings_percentages(settings):
    return {key: float(value) * 100.0 for key, value in asdict(settings).items()}


def root_settings_percentages(settings=DEFAULT_SETTINGS):
    values = settings_percentages(settings)
    return {
        "minimum_offset_percent": values["minimum_offset_ratio"],
        "collagen_depth_percent": values["collagen_depth_ratio"],
        "collagen_core_percent": values["collagen_core_ratio"],
        "collagen_falloff_percent": values["collagen_falloff_ratio"],
    }


def settings_payload(settings):
    return {key: float(value) for key, value in asdict(settings).items()}


def settings_from_payload(payload):
    values = dict(payload or {})
    defaults = settings_payload(DEFAULT_SETTINGS)
    return SkinSolverSettings(**{key: float(values.get(key, value)) for key, value in defaults.items()})


def resolved_distances(settings, length):
    scale = max(0.0, float(length))
    required = settings.minimum_offset_ratio * scale
    rest = required + (settings.collagen_depth_ratio * scale)
    inner = settings.collagen_core_ratio * scale
    outer = inner + (settings.collagen_falloff_ratio * scale)
    return required, rest, inner, outer


def resolved_solver_distances(settings, length):
    required, rest, inner, outer = resolved_distances(settings, length)
    return {
        "required_offset": required,
        "rest_offset": rest,
        "collagen_inner": inner,
        "collagen_outer": outer,
        "required_probe": REQUIRED_PROBE_RATIO * length,
        "rest_probe": REST_PROBE_RATIO * length,
        "blend_radius": BLEND_RADIUS_RATIO * length,
    }


def padding_ratio(settings):
    required, rest, inner, outer = resolved_distances(settings, 1.0)
    reach = max(REQUIRED_PROBE_RATIO + required, REST_PROBE_RATIO + rest, outer)
    return reach + PADDING_SAFETY_RATIO


def effective_collagen(mode, value, *names):
    if str(mode or "AUTO") != "AUTO":
        return min(1.0, max(0.0, float(value)))
    text = " ".join(str(name or "") for name in names).lower()
    return 0.0 if any(term in text for term in AUTO_ZERO_TERMS) else 1.0
