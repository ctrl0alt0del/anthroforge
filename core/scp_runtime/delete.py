from ..visualization.delete_reconcile import cleanup_scp_dependents
from .bound_objects import clear_scp_tags
from .common import find_scp_by_id, find_scp_index
from .marking import normalize_active_index


def delete_scp(root, scene, scp_id):
    scp = find_scp_by_id(root, scp_id)
    if scp is None:
        return False
    _clear_tags(scp)
    _remove_entry(root, scp_id)
    _clear_parent_picker(scene, scp_id)
    cleanup_scp_dependents(root)
    return True


def _clear_tags(scp):
    for entry in tuple(getattr(scp, "bound_objects", ())):
        clear_scp_tags(getattr(entry, "object_ref", None))


def _remove_entry(root, scp_id):
    index = find_scp_index(root, scp_id)
    if index >= 0:
        root.af_scp_system.scps.remove(index)
        normalize_active_index(root)


def _clear_parent_picker(scene, scp_id):
    obj = None if scene is None else getattr(scene, "af_scp_parent_obj", None)
    if obj and str(obj.get("af_scp_id") or "") == str(scp_id or ""):
        scene.af_scp_parent_obj = None
