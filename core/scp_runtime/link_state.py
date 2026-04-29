from .common import set_prop_raw

_FIELDS = (
    "parent_id",
    "attach_initialized",
    "attach_parent_tri_vidx",
    "attach_parent_tri_weights",
    "attach_parent_offset_local",
    "attach_child_origin_local",
    "attach_child_tangent_local",
    "attach_child_normal_local",
)


def snapshot_link_state(scp):
    return {field: _snapshot_value(getattr(scp, field, None)) for field in _FIELDS}


def _snapshot_value(value):
    return tuple(value) if isinstance(value, (list, tuple)) else value


def restore_link_state(scp, snapshot):
    for field, value in snapshot.items():
        set_prop_raw(scp, field, value)
