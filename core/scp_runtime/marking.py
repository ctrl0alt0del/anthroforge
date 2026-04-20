from ..id_utils import next_prefixed_id
from .common import as_id, find_source_scp_obj, is_source_scp, scp_prop_map
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
        return
    sync_scp_identity(scp, obj.name)


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


def _prune_indexes(root, scene):
    indexes = []
    for index, scp in enumerate(root.af_scp_system.scps):
        if find_source_scp_obj(scene, root.name, getattr(scp, "id", "")) is None:
            indexes.append(index)
    return indexes


def prune_invalid_scps(root, scene):
    for index in reversed(_prune_indexes(root, scene)):
        root.af_scp_system.scps.remove(index)


def detach_native_scp_parent_links(root, scene):
    for obj in scene.objects:
        parent = getattr(obj, "parent", None)
        if is_source_scp(obj, root.name) and is_source_scp(parent, root.name):
            clear_native_parent_keep_world(obj)


def sync_parent_links(root):
    sanitize_parent_links(root, scp_prop_map(root))


def normalize_active_index(root):
    count = len(root.af_scp_system.scps)
    index = int(getattr(root.af_scp_system, "active_scp_index", -1))
    root.af_scp_system.active_scp_index = -1 if count <= 0 else min(max(index, 0), count - 1)
