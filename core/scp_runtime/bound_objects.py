from ..id_utils import next_prefixed_id
from .common import as_id, set_prop_raw


def _entry_obj(entry):
    return None if entry is None else getattr(entry, "object_ref", None)


def _same_object(entry, obj):
    return _entry_obj(entry) == obj


def _identity_obj(scp):
    return getattr(scp, "transform_object_ref", None) or getattr(scp, "geometry_object_ref", None)


def _sync_identity(scp):
    obj = _identity_obj(scp)
    name = "" if obj is None else str(obj.name)
    set_prop_raw(scp, "name", name or as_id(getattr(scp, "id", "")))


def find_bound_entry_by_id(scp, bound_id):
    sid = as_id(bound_id)
    return next((entry for entry in scp.bound_objects if as_id(entry.id) == sid), None)


def find_bound_entry_by_object(scp, obj):
    return next((entry for entry in scp.bound_objects if _same_object(entry, obj)), None)


def iter_bound_objects(scp):
    for entry in getattr(scp, "bound_objects", ()):
        obj = _entry_obj(entry)
        if obj is not None:
            yield entry, obj


def clear_scp_tags(obj):
    if obj is None:
        return
    for key in ("af_root_name", "af_scp_id", "af_scp_bound", "af_scp_bound_id", "af_scp_transform", "af_scp_geometry"):
        if key in obj:
            del obj[key]


def _tag_object(root_name, scp, entry, obj):
    obj["af_root_name"] = root_name
    obj["af_scp_id"] = as_id(getattr(scp, "id", ""))
    obj["af_scp_bound"] = True
    obj["af_scp_bound_id"] = as_id(getattr(entry, "id", ""))
    obj["af_scp_transform"] = obj == getattr(scp, "transform_object_ref", None)
    obj["af_scp_geometry"] = obj == getattr(scp, "geometry_object_ref", None)


def _clear_missing_refs(scp, obj):
    if obj == getattr(scp, "geometry_object_ref", None):
        set_prop_raw(scp, "geometry_object_ref", None)
    if obj == getattr(scp, "transform_object_ref", None):
        set_prop_raw(scp, "transform_object_ref", None)


def _remove_bound_index(scp, index):
    obj = _entry_obj(scp.bound_objects[index])
    _clear_missing_refs(scp, obj)
    scp.bound_objects.remove(index)
    clear_scp_tags(obj) if obj is not None else None


def _other_owner(root, scp, obj):
    for other in root.af_scp_system.scps:
        if other != scp and find_bound_entry_by_object(other, obj) is not None:
            return other
    return None


def _remove_object_from_scp(scp, obj):
    indexes = [i for i, entry in enumerate(scp.bound_objects) if _same_object(entry, obj)]
    for index in reversed(indexes):
        _remove_bound_index(scp, index)
    _sync_identity(scp)


def _new_bound_entry(scp, obj):
    entry = scp.bound_objects.add()
    entry.id = next_prefixed_id(scp.bound_objects, "OBJ")
    entry.object_ref = obj
    entry.label = str(obj.name)
    return entry


def ensure_bound_object(root, scp, obj):
    if obj is None:
        return None
    if _other_owner(root, scp, obj) is not None:
        return None
    entry = find_bound_entry_by_object(scp, obj) or _new_bound_entry(scp, obj)
    _sync_identity(scp)
    return entry


def _parent_keep_world(obj, parent):
    if obj is None or parent is None or obj == parent:
        return
    world = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted()
    obj.matrix_world = world


def _sync_parenting(scp):
    parent = getattr(scp, "transform_object_ref", None)
    for _entry, obj in iter_bound_objects(scp):
        _parent_keep_world(obj, parent) if parent and obj != parent else None


def sync_scp_roles(root, scp):
    for obj in list(_live_bound_objects(scp)):
        clear_scp_tags(obj)
    _ensure_role_entries(root, scp)
    for entry, obj in iter_bound_objects(scp):
        _tag_object(root.name, scp, entry, obj)
    _sync_parenting(scp)
    _sync_identity(scp)


def _live_bound_objects(scp):
    return [_entry_obj(entry) for entry in scp.bound_objects if _entry_obj(entry) is not None]


def _ensure_role_entries(root, scp):
    for obj in (getattr(scp, "transform_object_ref", None), getattr(scp, "geometry_object_ref", None)):
        ensure_bound_object(root, scp, obj) if obj is not None else None


def set_transform_object(root, scp, obj):
    if ensure_bound_object(root, scp, obj) is None:
        return False
    set_prop_raw(scp, "transform_object_ref", obj)
    sync_scp_roles(root, scp)
    return True


def set_geometry_object(root, scp, obj):
    if obj is not None and ensure_bound_object(root, scp, obj) is None:
        return False
    set_prop_raw(scp, "geometry_object_ref", obj)
    sync_scp_roles(root, scp)
    return True


def remove_bound_object(root, scp, bound_id):
    entry = find_bound_entry_by_id(scp, bound_id)
    obj = _entry_obj(entry)
    if entry is None or obj == getattr(scp, "transform_object_ref", None):
        return False
    _remove_object_from_scp(scp, obj)
    sync_scp_roles(root, scp)
    return True


def sync_all_scp_roles(root):
    for scp in root.af_scp_system.scps:
        sync_scp_roles(root, scp)
