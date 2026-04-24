from .common import set_prop_raw

_ATTACH_DEFAULTS = (
    ("attach_child_anchor_mode", "FACE_CENTER"),
    ("attach_follow_rotation", True),
    ("attach_initialized", False),
    ("attach_parent_tri_vidx", (-1, -1, -1)),
    ("attach_parent_tri_weights", (1.0, 0.0, 0.0)),
    ("attach_child_origin_local", (0.0, 0.0, 0.0)),
    ("attach_child_tangent_local", (1.0, 0.0, 0.0)),
    ("attach_child_normal_local", (0.0, 0.0, 1.0)),
)
_MIRROR_DEFAULTS = (
    ("mirror_enabled", False),
    ("mirror_axis", "X"),
    ("mirror_origin", (0.0, 0.0, 0.0)),
    ("mirror_status", "NONE"),
    ("mirror_source_id", ""),
    ("mirror_effective_axis", "X"),
)


def _apply_defaults(prop, pairs):
    for key, value in pairs:
        set_prop_raw(prop, key, value)


def reset_attachment_state(prop):
    _apply_defaults(prop, _ATTACH_DEFAULTS)


def reset_mirror_state(prop):
    _apply_defaults(prop, _MIRROR_DEFAULTS)


def initialize_scp_entry(prop, scp_id, object_name):
    set_prop_raw(prop, "id", scp_id)
    set_prop_raw(prop, "name", object_name)
    set_prop_raw(prop, "object_name", object_name)
    set_prop_raw(prop, "parent_id", "")
    reset_attachment_state(prop)
    reset_mirror_state(prop)


def sync_scp_identity(prop, object_name):
    set_prop_raw(prop, "name", object_name)
    set_prop_raw(prop, "object_name", object_name)
