from .common import as_id, scp_prop_map, set_prop_raw
from .runtime_state import reset_attachment_runtime


def has_parent_cycle(start_id, scp_by_id):
    seen = set()
    current = as_id(start_id)
    while current:
        if current in seen:
            return True
        seen.add(current)
        current = as_id(getattr(scp_by_id.get(current), "parent_id", ""))
    return False


def children_map(scp_by_id):
    children = {sid: [] for sid in scp_by_id}
    for sid, scp in scp_by_id.items():
        pid = as_id(getattr(scp, "parent_id", ""))
        if pid and pid in children and pid != sid:
            children[pid].append(sid)
    for child_ids in children.values():
        child_ids.sort()
    return children


def _depth_of(sid, scp_by_id, cache):
    if sid in cache:
        return cache[sid]
    pid = as_id(getattr(scp_by_id.get(sid), "parent_id", ""))
    cache[sid] = 0 if not pid or pid not in scp_by_id or pid == sid else _depth_of(pid, scp_by_id, cache) + 1
    return cache[sid]


def children_depth_order(scp_by_id):
    cache = {}
    keys = list(scp_by_id.keys())
    keys.sort(key=lambda sid: (_depth_of(sid, scp_by_id, cache), sid))
    return keys


def root_ids(scp_by_id):
    roots = [sid for sid, scp in scp_by_id.items() if as_id(getattr(scp, "parent_id", "")) not in scp_by_id]
    roots.sort()
    return roots


def _invalid_parent_ids(root, scp_by_id):
    invalid = set()
    for scp in root.af_scp_system.scps:
        sid = as_id(getattr(scp, "id", ""))
        pid = as_id(getattr(scp, "parent_id", ""))
        if pid and (pid == sid or pid not in scp_by_id or has_parent_cycle(sid, scp_by_id)):
            invalid.add(sid)
    return invalid


def _clear_parent_ids(root, invalid_ids):
    for scp in root.af_scp_system.scps:
        if as_id(getattr(scp, "id", "")) in invalid_ids:
            set_prop_raw(scp, "parent_id", "")
            reset_attachment_runtime(scp)


def sanitize_parent_links(root, scp_by_id):
    changed = set()
    while True:
        invalid_ids = _invalid_parent_ids(root, scp_by_id)
        if not invalid_ids:
            return changed, scp_prop_map(root)
        _clear_parent_ids(root, invalid_ids)
        changed |= invalid_ids
        scp_by_id = scp_prop_map(root)
