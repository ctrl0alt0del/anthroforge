from .common import set_prop_raw
from .prop_update_guard import set_parent_id_raw
from .runtime_state import reset_attachment_runtime, reset_mirror_runtime

_ATTACH_DEFAULTS = (
    ("attach_parent_anchor_mode", "SURFACE_NEAREST"),
    ("attach_child_anchor_mode", "FACE_CENTER"),
    ("attach_follow_rotation", True),
    ("attach_tangent_strategy", "AUTO"),
)
_MIRROR_DEFAULTS = (
    ("mirror_enabled", False),
    ("mirror_inherit_parent", True),
    ("mirror_axis", "X"),
    ("mirror_origin", (0.0, 0.0, 0.0)),
)
_COLOR_DEFAULTS = (
    ("color", (0.0, 0.0, 0.0, 1.0)),
    ("color_initialized", False),
)


def _apply_defaults(prop, pairs):
    for key, value in pairs:
        set_prop_raw(prop, key, value)


def reset_attachment_state(prop):
    _apply_defaults(prop, _ATTACH_DEFAULTS)
    reset_attachment_runtime(prop)


def reset_mirror_state(prop):
    _apply_defaults(prop, _MIRROR_DEFAULTS)
    reset_mirror_runtime(prop)


def reset_color_state(prop):
    _apply_defaults(prop, _COLOR_DEFAULTS)


def initialize_scp_entry(prop, scp_id, label):
    set_prop_raw(prop, "id", scp_id)
    set_prop_raw(prop, "name", label)
    set_parent_id_raw(prop, "")
    reset_color_state(prop)
    reset_attachment_state(prop)
    reset_mirror_state(prop)
