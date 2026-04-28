from ..id_utils import next_prefixed_id
from .bound_objects import set_geometry_object, set_transform_object, sync_all_scp_roles
from .common import as_id, find_source_scp_obj, is_source_scp, is_transform_scp_obj, scp_prop_map
from .defaults import initialize_scp_entry, sync_scp_identity
from .lookup import clear_native_parent_keep_world
from .tree import sanitize_parent_links


def _sync_discovered_entry(scp_by_id, obj, root):
    sid = _ensure_discovered_id(obj, root)
    scp = scp_by_id.get(sid)
    if scp is None:
        scp = root.af_scp_system.scps.add()
        initialize_scp_entry(scp, sid, obj.name)
        scp_by_id[sid] = scp
    sync_scp_identity(scp, obj.name)
    _seed_legacy_roles(root, scp, obj)


def _seed_legacy_roles(root, scp, obj):
    if getattr(scp, "transform_object_ref", None) is None:
        set_transform_object(root, scp, obj)
    if getattr(scp, "geometry_object_ref", None) is None:
        set_geometry_object(root, scp, obj)


def _ensure_discovered_id(obj, root):
    sid = as_id(obj.get("af_scp_id"))
    if sid:
        return sid
    sid = next_prefixed_id(root.af_scp_system.scps, "SCP")
    obj["af_scp_id"] = sid
    return sid


def discover_marked_scps(root, scene):
    scp_by_id = scp_prop_map(root)
    for obj in scene.objects:
        if is_source_scp(obj, root.name):
            _sync_discovered_entry(scp_by_id, obj, root)
    sync_all_scp_roles(root)


def _prune_indexes(root, scene):
    indexes = []
    for index, scp in enumerate(root.af_scp_system.scps):
        if _should_prune_scp(scene, root.name, scp):
            indexes.append(index)
    return indexes


def _should_prune_scp(scene, root_name, scp):
    if _has_live_roles(scp):
        return False
    return find_source_scp_obj(scene, root_name, getattr(scp, "id", "")) is None


def _has_live_roles(scp):
    refs = [getattr(scp, "transform_object_ref", None), getattr(scp, "geometry_object_ref", None)]
    refs += [getattr(entry, "object_ref", None) for entry in getattr(scp, "bound_objects", ())]
    return any(obj is not None for obj in refs)


def prune_invalid_scps(root, scene):
    for index in reversed(_prune_indexes(root, scene)):
        root.af_scp_system.scps.remove(index)


def detach_native_scp_parent_links(root, scene):
    for obj in scene.objects:
        parent = getattr(obj, "parent", None)
        if is_transform_scp_obj(obj, root.name) and is_transform_scp_obj(parent, root.name):
            clear_native_parent_keep_world(obj)


def sync_parent_links(root):
    sanitize_parent_links(root, scp_prop_map(root))


def normalize_active_index(root):
    count = len(root.af_scp_system.scps)
    index = int(getattr(root.af_scp_system, "active_scp_index", -1))
    target = -1 if count <= 0 else min(max(index, 0), count - 1)
    if target != index:
        root.af_scp_system.active_scp_index = target
