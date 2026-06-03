from ..id_utils import next_prefixed_id
from ..shortcuts.path_codec import make_shortcut_path


_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}
_AXIS_LABEL = {"X": "X", "Y": "Y", "Z": "Z"}


def _axis_value(axis):
    value = str(axis or "").upper()
    return value if value in _AXIS_INDEX else ""


def axis_shortcut_name(obj, axis):
    value = _axis_value(axis)
    return "" if obj is None or not value else f"{obj.name} Position {_AXIS_LABEL[value]}"


def axis_shortcut_path(obj, axis):
    value = _axis_value(axis)
    if obj is None or not value:
        return ""
    axis_index = _AXIS_INDEX[value]
    return make_shortcut_path("object_rna", f"location[{int(axis_index)}]", entity_id=str(obj.name))


def _find_shortcut(root, data_path):
    needle = str(data_path or "")
    for item in root.af_shortcut_system.shortcuts:
        if str(getattr(item, "data_path", "") or "") == needle:
            return item
    return None


def has_axis_shortcut(root, obj, axis):
    if root is None or obj is None or not _axis_value(axis):
        return False
    return _find_shortcut(root, axis_shortcut_path(obj, axis)) is not None


def _remove_shortcut(root, shortcut_id):
    sid = str(shortcut_id or "")
    for index, item in enumerate(root.af_shortcut_system.shortcuts):
        if str(getattr(item, "id", "") or "") == sid:
            root.af_shortcut_system.shortcuts.remove(index)
            return True
    return False


def _add_shortcut(root, name, data_path, owner_type, owner_id):
    item = root.af_shortcut_system.shortcuts.add()
    item.id = next_prefixed_id(root.af_shortcut_system.shortcuts, "SHORTCUT")
    item.name = str(name or "").strip()
    item.owner_type = str(owner_type or "NONE")
    item.owner_id = str(owner_id or "")
    item.data_path = str(data_path or "")


def _owner_from_object(obj):
    if obj is None:
        return "NONE", ""
    if obj.get("af_scp_id"):
        return "SCP", str(obj.get("af_scp_id"))
    if obj.get("af_fiber_id"):
        return "FIBER", str(obj.get("af_fiber_id"))
    if obj.get("af_muscle_id"):
        return "MUSCLE", str(obj.get("af_muscle_id"))
    if obj.get("af_blob_id"):
        return "BLOB", str(obj.get("af_blob_id"))
    return "NONE", ""


def _resolved_owner(obj, fallback_owner):
    owner_type, owner_id = _owner_from_object(obj)
    if owner_type != "NONE" and owner_id:
        return owner_type, owner_id
    f_type, f_id = fallback_owner if fallback_owner is not None else ("NONE", "")
    f_type = str(f_type or "NONE")
    f_id = str(f_id or "")
    return (f_type, f_id) if f_type != "NONE" and f_id else ("NONE", "")


def toggle_axis_shortcut(root, obj, axis, fallback_owner=None):
    if root is None or obj is None or not _axis_value(axis):
        return False, "Invalid control object or axis."

    data_path = axis_shortcut_path(obj, axis)
    existing = _find_shortcut(root, data_path)
    if existing is not None:
        _remove_shortcut(root, existing.id)
        return True, ""

    owner_type, owner_id = _resolved_owner(obj, fallback_owner)
    if owner_type == "NONE" or not owner_id:
        return False, "Could not resolve shortcut owner. Pick an SCP or select a VCP entity first."

    _add_shortcut(
        root=root,
        name=axis_shortcut_name(obj, axis),
        data_path=data_path,
        owner_type=owner_type,
        owner_id=owner_id,
    )
    return True, ""
