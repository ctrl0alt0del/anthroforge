from ..shortcuts.session_state import active_follow_rotation_override, active_rotation_strategy_override
from .common import as_bool, as_id

_STRATEGIES = {"AUTO", "STABLE_SURFACE", "DEFORMATION_FLOW"}


def follow_rotation_enabled(child_scp):
    override = active_follow_rotation_override(child_scp)
    return override if override is not None else as_bool(getattr(child_scp, "attach_follow_rotation", True), default=True)


def tangent_strategy(child_scp):
    override = active_rotation_strategy_override(child_scp)
    if override in _STRATEGIES:
        return override
    mode = as_id(getattr(child_scp, "attach_tangent_strategy", "AUTO")).upper()
    return mode if mode in _STRATEGIES else "AUTO"
