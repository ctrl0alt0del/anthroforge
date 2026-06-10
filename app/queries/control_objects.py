from dataclasses import dataclass, field

try:
    from ...core.control_flags import is_control_object
    from ...core.visualization.control_object_shortcuts import has_axis_shortcut
    from ...core.scp_runtime.common import find_scp_by_id, scp_for_object
except ImportError:
    from core.control_flags import is_control_object
    from core.visualization.control_object_shortcuts import has_axis_shortcut
    from core.scp_runtime.common import find_scp_by_id, scp_for_object

from .scp import active_scp_from_context
from .root import root_for_context


@dataclass(frozen=True)
class ControlAxisState:
    axis: str = ""
    checked: bool = False


@dataclass(frozen=True)
class ControlPanelState:
    root: object = None
    obj: object = None
    picked: object = None
    is_control: bool = False
    apply_parent: bool = False
    axis_states: tuple = field(default_factory=tuple)


def active_object(context):
    return None if context is None else getattr(context, "active_object", None)


def picked_control_scp(context):
    scene = None if context is None else getattr(context, "scene", None)
    return None if scene is None else getattr(scene, "af_control_scp_obj", None)


def _axis_states(root, obj):
    return tuple(ControlAxisState(axis, has_axis_shortcut(root, obj, axis)) for axis in ("X", "Y", "Z"))


def _picked_scp(root, context):
    picked = picked_control_scp(context)
    scp = None if picked is None else scp_for_object(root, picked)
    return scp if scp is not None else active_scp_from_context(context)


def _control_scp(root, context, obj):
    sid = "" if obj is None else str(obj.get("af_scp_id") or "")
    return find_scp_by_id(root, sid) if sid else _picked_scp(root, context)


def _apply_parent_state(root, context, obj, is_control):
    scp = None if not is_control else _control_scp(root, context, obj)
    parent = None if scp is None else getattr(scp, "transform_object_ref", None)
    return bool(parent is not None and getattr(obj, "parent", None) == parent)


def control_panel_state(context):
    root = root_for_context(context)
    obj = active_object(context)
    is_control = is_control_object(obj)
    return ControlPanelState(
        root=root,
        obj=obj,
        picked=picked_control_scp(context),
        is_control=is_control,
        apply_parent=_apply_parent_state(root, context, obj, is_control),
        axis_states=() if not is_control else _axis_states(root, obj),
    )
