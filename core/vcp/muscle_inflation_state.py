"""Durable authored inflation placement, independent of transient controls."""

from math import isfinite

from .prop_update_guard import suppress_vcp_prop_updates

WORLD_KEY = "inflation_ctrl_world"
INITIALIZED_KEY = "inflation_ctrl_initialized"
LEGACY_KEY = "_af_rt_muscle_inflation_ctrl_world"
_MISSING = object()


def _stored(muscle, key, default=_MISSING):
    getter = getattr(muscle, "get", None)
    return getter(key, default) if getter else getattr(muscle, key, default)


def _write(muscle, key, value):
    if hasattr(muscle, key) or not hasattr(muscle, "__setitem__"):
        setattr(muscle, key, value)
    else:
        muscle[key] = value


def _point(value):
    try:
        point = tuple(float(component) for component in value)
    except (TypeError, ValueError, OverflowError):
        return None
    return point if len(point) == 3 and all(isfinite(component) for component in point) else None


def migrate_inflation_control(muscle):
    """Explicit new state wins; migrate only present, valid legacy coordinates."""
    initialized = _stored(muscle, INITIALIZED_KEY)
    if initialized is not _MISSING:
        return bool(initialized)
    point = _point(_stored(muscle, LEGACY_KEY, None))
    if point is None:
        return False
    set_inflation_control_world(muscle, point)
    return True


def inflation_control_initialized(muscle):
    return migrate_inflation_control(muscle)


def inflation_control_world(muscle):
    migrate_inflation_control(muscle)
    return _point(_stored(muscle, WORLD_KEY, (0.0, 0.0, 0.0))) or (0.0, 0.0, 0.0)


def set_inflation_control_world(muscle, value):
    point = _point(value)
    if point is None:
        raise ValueError("Inflation control must contain three finite coordinates.")
    with suppress_vcp_prop_updates():
        _write(muscle, WORLD_KEY, point)
        _write(muscle, INITIALIZED_KEY, True)
