from .common import is_transform_scp_obj, scp_prop_map, set_prop_raw
from .lookup import clear_native_parent_keep_world
from .tree import sanitize_parent_links

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
        set_prop_raw(root.af_scp_system, "active_scp_index", target)
