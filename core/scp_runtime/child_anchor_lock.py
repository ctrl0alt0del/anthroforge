from .common import set_prop_raw

_KEYS = {"FACE_CENTER": "attach_child_face_lock_index", "VERTEX_NEAREST": "attach_child_vertex_lock_index"}


def lock_prop_name(mode):
    return _KEYS.get(str(mode or "").upper(), "")


def locked_child_anchor_index(scp, mode):
    key = lock_prop_name(mode)
    return -1 if not key else int(getattr(scp, key, -1))


def set_locked_child_anchor_index(scp, mode, index):
    key = lock_prop_name(mode)
    if scp is None or not key:
        return
    set_prop_raw(scp, key, int(index))


def clear_locked_child_anchor_index(scp, mode):
    set_locked_child_anchor_index(scp, mode, -1)


def has_locked_child_anchor(scp, mode):
    return locked_child_anchor_index(scp, mode) >= 0
