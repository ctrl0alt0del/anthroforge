from dataclasses import dataclass

try:
    from ...core.local_transform_props import local_transform_state
except ImportError:
    from core.local_transform_props import local_transform_state


@dataclass(frozen=True)
class LocalTransformPanelState:
    has_object: bool = False
    active_name: str = ""
    installed: bool = False
    has_props: bool = False
    has_conflict: bool = False
    message: str = ""


def local_transform_panel_state(context):
    obj = None if context is None else getattr(context, "active_object", None)
    state = local_transform_state(obj)
    return LocalTransformPanelState(bool(obj), _name(obj), state.installed, state.has_props, state.has_conflict, state.message)


def _name(obj):
    return "" if obj is None else str(getattr(obj, "name", "") or "")
