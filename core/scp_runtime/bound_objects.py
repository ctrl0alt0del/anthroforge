import bpy

from ..id_utils import next_prefixed_id
from ..utils import scene_for_id
from .common import as_id, invalidate_scp_object_maps, invalidate_scp_prop_map, set_prop_raw
from .object_colors import apply_object_color, ensure_scp_color
from .prop_update_guard import suppress_scp_prop_updates


def _entry_obj(entry):
    return None if entry is None else getattr(entry, "object_ref", None)


def _entry_native_parenting(entry):
    return bool(getattr(entry, "native_parenting_enabled", True))


def _same_object(entry, obj):
    return _entry_obj(entry) == obj


def _identity_obj(scp):
    return getattr(scp, "transform_object_ref", None) or getattr(scp, "geometry_object_ref", None)


def _sync_identity(scp):
    obj = _identity_obj(scp)
    name = "" if obj is None else str(obj.name)
    target = name or as_id(getattr(scp, "id", ""))
    if str(getattr(scp, "name", "")) == target:
        return
    with suppress_scp_prop_updates():
        set_prop_raw(scp, "name", target)


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
    entry.native_parenting_enabled = True
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
    if obj is None or parent is None or obj == parent or getattr(obj, "parent", None) == parent:
        return
    world = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted()
    obj.matrix_world = world


def _clear_parent_keep_world(obj, parent):
    if obj is None or parent is None or getattr(obj, "parent", None) != parent:
        return
    world = obj.matrix_world.copy()
    obj.parent = None
    obj.matrix_world = world


def _sync_parenting(scp):
    parent = getattr(scp, "transform_object_ref", None)
    for entry, obj in iter_bound_objects(scp):
        if not parent or obj == parent:
            continue
        if _entry_native_parenting(entry):
            _parent_keep_world(obj, parent)
        else:
            _clear_parent_keep_world(obj, parent)


def _root_host_collection(root):
    cols = tuple(getattr(root, "users_collection", ()) or ())
    if cols:
        return cols[0]
    scene = scene_for_id(root)
    return None if scene is None else scene.collection


def _unlinked_collection_name(root, scp):
    root_name = str(getattr(root, "name", "AF_ROOT") or "AF_ROOT")
    scp_name = str(getattr(scp, "name", "") or "").strip()
    scp_id = as_id(getattr(scp, "id", ""))
    scp_token = scp_id or scp_name or "SCP"
    return f"{root_name}_{scp_token}_UNLINKED"


def _ensure_unlinked_collection(root, scp):
    name = _unlinked_collection_name(root, scp)
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
    host = _root_host_collection(root)
    if host is not None and host.children.get(col.name) is None:
        host.children.link(col)
    return col


def _move_object_to_collection(obj, target):
    if obj is None or target is None:
        return
    if target.objects.get(obj.name) is None:
        target.objects.link(obj)
    for col in tuple(getattr(obj, "users_collection", ()) or ()):  # preserve a single clear home collection
        if col != target:
            try:
                col.objects.unlink(obj)
            except Exception:
                pass


def _route_bound_object_collection(root, scp, obj, native_parenting_enabled):
    target = _root_host_collection(root) if bool(native_parenting_enabled) else _ensure_unlinked_collection(root, scp)
    _move_object_to_collection(obj, target)


def _sync_color(root, scp):
    color = ensure_scp_color(root, scp)
    for _entry, obj in iter_bound_objects(scp):
        apply_object_color(obj, color)


def _invalidate_object_index(root):
    scene = scene_for_id(root)
    invalidate_scp_object_maps(scene, root.name)
    invalidate_scp_prop_map(root)


def sync_scp_roles(root, scp, invalidate=True):
    for obj in list(_live_bound_objects(scp)):
        clear_scp_tags(obj)
    _ensure_role_entries(root, scp)
    for entry, obj in iter_bound_objects(scp):
        _tag_object(root.name, scp, entry, obj)
    _sync_parenting(scp)
    _sync_identity(scp)
    _sync_color(root, scp)
    _invalidate_object_index(root) if invalidate else None


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


def set_bound_native_parenting(root, scp, bound_id, enabled):
    entry = find_bound_entry_by_id(scp, bound_id)
    obj = _entry_obj(entry)
    if entry is None or obj is None:
        return False
    if obj == getattr(scp, "transform_object_ref", None):
        return False
    value = bool(enabled)
    if _entry_native_parenting(entry) == value:
        return True
    set_prop_raw(entry, "native_parenting_enabled", value)
    sync_scp_roles(root, scp)
    _route_bound_object_collection(root, scp, obj, value)
    return True


def sync_all_scp_roles(root):
    for scp in root.af_scp_system.scps:
        sync_scp_roles(root, scp, invalidate=False)
    _invalidate_object_index(root)


def sync_scp_roles_for_ids(root, scp_ids):
    wanted = {as_id(value) for value in set(scp_ids or set()) if as_id(value)}
    if not wanted:
        return
    for scp in root.af_scp_system.scps:
        sync_scp_roles(root, scp, invalidate=False) if as_id(scp.id) in wanted else None
    _invalidate_object_index(root)
