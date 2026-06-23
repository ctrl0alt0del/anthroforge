from dataclasses import dataclass
import bpy

try:
    from ...core.local_transform_props import local_transform_state
    from ...core.action_library_split_corner import split_corner_spec
except ImportError:
    from core.local_transform_props import local_transform_state
    from core.action_library_split_corner import split_corner_spec


@dataclass(frozen=True)
class LocalTransformPanelState:
    has_object: bool = False
    active_name: str = ""
    installed: bool = False
    has_props: bool = False
    has_conflict: bool = False
    message: str = ""


@dataclass(frozen=True)
class CurveLoftPanelState:
    has_scene: bool = False
    name: str = ""
    curve_count: int = 0
    can_create: bool = False
    message: str = ""


@dataclass(frozen=True)
class SplitCornerPanelState:
    can_split: bool = False
    message: str = ""


def local_transform_panel_state(context):
    obj = None if context is None else getattr(context, "active_object", None)
    state = local_transform_state(obj)
    return LocalTransformPanelState(bool(obj), _name(obj), state.installed, state.has_props, state.has_conflict, state.message)


def curve_loft_panel_state(context):
    scene = None if context is None else getattr(context, "scene", None)
    name = _scene_text(scene, "af_action_gn_name")
    count = int(getattr(scene, "af_action_curve_count", 0) or 0) if scene else 0
    conflict = _group_conflict(name)
    exists = _group_exists(name)
    ready = bool(scene and name and count >= 2 and not conflict)
    message = _curve_loft_message(name, count, exists, conflict)
    return CurveLoftPanelState(bool(scene), name, count, ready, message)


def split_corner_panel_state(context):
    _spec, error = split_corner_spec(context)
    message = error or "Split the selected curve corners into SCP segments with shared parent controls."
    return SplitCornerPanelState(not error, message)


def _name(obj):
    return "" if obj is None else str(getattr(obj, "name", "") or "")


def _scene_text(scene, attr):
    return "" if scene is None else str(getattr(scene, attr, "") or "").strip()


def _curve_loft_message(name, count, exists, conflict):
    if not name:
        return "Enter a node group name."
    if count < 2:
        return "Curve count must be at least 2."
    if conflict:
        return f'Node group "{name}" exists but is not a Geometry Nodes group.'
    if exists:
        return f'Node group "{name}" exists. Create will ask to overwrite.'
    return "Create a generated loft group from curve inputs."


def _group_exists(name):
    return bool(name and bpy.data.node_groups.get(name))


def _group_conflict(name):
    group = bpy.data.node_groups.get(name) if name else None
    return bool(group and str(getattr(group, "bl_idname", "")) != "GeometryNodeTree")
