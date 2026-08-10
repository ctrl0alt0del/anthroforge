from ..selection import get_active_af_entity, get_active_scp
from ..scp_runtime.common import scp_prop_map
from ..scp_runtime.tree import ancestor_ids

_OWNER_KEYS = {"SCP": "scps", "FIBER": "fibers", "MUSCLE": "muscles", "BLOB": "blobs",
               "SOFT_TISSUE": "soft_tissues"}


def current_shortcut_owner(root, context):
    kind, owner_id = get_active_af_entity(root, context)
    owner_id = str(owner_id or "")
    return (kind, owner_id) if kind in _OWNER_KEYS and owner_id else ("NONE", "")


def shortcut_owner(shortcut):
    kind = str(getattr(shortcut, "owner_type", "NONE") or "NONE")
    owner_id = str(getattr(shortcut, "owner_id", "") or "")
    return (kind, owner_id) if kind in _OWNER_KEYS and owner_id else ("NONE", "")


def matches_shortcut_owner(shortcut, kind, owner_id):
    return str(kind or "NONE") != "NONE" and shortcut_owner(shortcut) == (str(kind or "NONE"), str(owner_id or ""))


def remapped_shortcut_owner(shortcut, maps):
    kind, owner_id = shortcut_owner(shortcut)
    key = _OWNER_KEYS.get(kind, "")
    new_id = dict(maps.get(key, {}) or {}).get(owner_id, "")
    return (kind, new_id) if new_id else ("NONE", "")


def selected_scp_id(root, context):
    scp = get_active_scp(root, context)
    return str(getattr(scp, "id", "") or "")


def shortcut_relation(root, shortcut, target_scp_id):
    kind, owner_id = shortcut_owner(shortcut)
    if kind != "SCP" or not target_scp_id:
        return "UNRELATED"
    if owner_id == str(target_scp_id or ""):
        return "SELF"
    return "ANCESTOR" if owner_id in ancestor_ids(scp_prop_map(root), target_scp_id) else "UNRELATED"
