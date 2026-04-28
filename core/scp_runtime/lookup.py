from ..id_utils import next_prefixed_id
from .common import find_scp_by_id, find_scp_index, is_transform_scp_obj, scp_for_object
from .common import scp_prop_map, set_prop_raw
from .defaults import initialize_scp_entry

def mark_source_tags(obj, root_name, scp_id):
    obj["af_scp"] = True
    obj["af_root_name"] = root_name
    obj["af_scp_id"] = scp_id


def clear_native_parent_keep_world(obj):
    if obj is None or getattr(obj, "parent", None) is None:
        return
    world = obj.matrix_world.copy()
    obj.parent = None
    obj.matrix_world = world


def effective_parent_obj(scene, root):
    parent_obj = getattr(scene, "af_scp_parent_obj", None)
    return parent_obj if is_transform_scp_obj(parent_obj, root.name) else None


def would_create_parent_cycle(root, child_scp_id, parent_scp_id):
    child_id = str(child_scp_id or "")
    parent_id = str(parent_scp_id or "")
    if not child_id or not parent_id:
        return False
    if child_id == parent_id:
        return True
    scp_by_id = scp_prop_map(root)
    current = parent_id
    while current and current in scp_by_id:
        if current == child_id:
            return True
        current = str(getattr(scp_by_id[current], "parent_id", "") or "")
    return False


def _existing_collection_entry(root, obj):
    return scp_for_object(root, obj)


def ensure_collection_entry(root, obj):
    scp = _existing_collection_entry(root, obj)
    if scp is None:
        scp = root.af_scp_system.scps.add()
        initialize_scp_entry(scp, next_prefixed_id(root.af_scp_system.scps, "SCP"), obj.name)
        return scp, True
    set_prop_raw(scp, "name", obj.name)
    set_prop_raw(scp, "object_name", obj.name)
    return scp, False


def set_parent_relation(child_obj, child_scp, parent_obj):
    clear_native_parent_keep_world(child_obj)
    parent_id = "" if parent_obj is None else str(parent_obj.get("af_scp_id") or "")
    set_prop_raw(child_scp, "parent_id", parent_id)
    set_prop_raw(child_scp, "attach_initialized", False)


def activate_scp(root, scp_id):
    index = find_scp_index(root, scp_id)
    if index >= 0:
        root.af_scp_system.active_scp_index = index
