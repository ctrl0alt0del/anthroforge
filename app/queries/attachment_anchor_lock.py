from dataclasses import dataclass

try:
    from ...core.scp_runtime.child_anchor_lock import locked_child_anchor_index
except ImportError:
    from core.scp_runtime.child_anchor_lock import locked_child_anchor_index


@dataclass(frozen=True)
class ChildAnchorLockPanelState:
    visible: bool = False
    mode: str = ""
    can_set: bool = False
    has_lock: bool = False
    invalid_lock: bool = False
    lock_index: int = -1
    selected_index: int = -1
    message: str = ""


def child_anchor_lock_panel_state(context, scp):
    mode = _lock_mode(scp)
    if not mode:
        return ChildAnchorLockPanelState()
    geo, lock_index = _geo(scp), locked_child_anchor_index(scp, mode)
    selected = _selected_index(context, geo, mode)
    invalid = lock_index >= 0 and not _valid_index(geo, mode, lock_index)
    can_set = geo is not None and selected >= 0
    return ChildAnchorLockPanelState(True, mode, can_set, lock_index >= 0, invalid, lock_index, selected, _message(context, geo, mode, selected, lock_index, invalid))


def _lock_mode(scp):
    mode = "" if scp is None else str(getattr(scp, "attach_child_anchor_mode", "") or "").upper()
    has_parent = bool(scp and str(getattr(scp, "parent_id", "") or ""))
    return mode if has_parent and mode in {"FACE_CENTER", "VERTEX_NEAREST"} else ""


def _geo(scp):
    obj = None if scp is None else getattr(scp, "geometry_object_ref", None)
    return obj if obj and obj.type == "MESH" else None


def _selected_index(context, obj, mode):
    if obj is None or not _edit_target(context, obj):
        return -1
    return _selected_mesh_index(obj, mode)


def _edit_target(context, obj):
    return bool(context and getattr(context, "mode", "") == "EDIT_MESH" and getattr(context, "active_object", None) == obj)


def _selected_mesh_index(obj, mode):
    import bmesh

    bm = bmesh.from_edit_mesh(obj.data)
    items = bm.faces if mode == "FACE_CENTER" else bm.verts
    items.ensure_lookup_table()
    items.index_update()
    chosen = [item.index for item in items if item.select]
    return chosen[0] if len(chosen) == 1 else -1


def _valid_index(obj, mode, index):
    count = 0 if obj is None else (len(obj.data.polygons) if mode == "FACE_CENTER" else len(obj.data.vertices))
    return 0 <= int(index) < count


def _message(context, obj, mode, selected, lock_index, invalid):
    if obj is None:
        return "Child anchor lock requires a mesh geometry object."
    if invalid:
        return f"Locked {_label(mode).lower()} no longer exists. Clear it or set a new one."
    if not _edit_target(context, obj):
        return f"Edit {obj.name} and select one {_label(mode).lower()} to lock."
    if selected < 0:
        return f"Select exactly one {_label(mode).lower()} to lock."
    if lock_index >= 0:
        return f"Locked {_label(mode).lower()} {lock_index}. Set will replace it."
    return f"Lock the attachment to selected {_label(mode).lower()} {selected}."


def _label(mode):
    return "face" if mode == "FACE_CENTER" else "vertex"
