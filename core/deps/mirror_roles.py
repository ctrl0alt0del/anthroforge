STATUS_NONE = "NONE"
STATUS_SOURCE = "SOURCE"
STATUS_TARGET = "TARGET"


def _as_id(value):
    return str(value or "")


def _as_axis(value):
    axis = str(value or "X").upper()
    return axis if axis in {"X", "Y", "Z"} else "X"


def _scp_map(root):
    return {_as_id(s.id): s for s in root.af_scp_system.scps}


def _set_prop_raw(scp_prop, key, value):
    try:
        scp_prop[key] = value
    except Exception:
        try:
            setattr(scp_prop, key, value)
        except Exception:
            pass


def _has_cycle_from(start_id, scp_by_id):
    cur = _as_id(start_id)
    seen = set()
    while cur:
        if cur in seen:
            return True
        seen.add(cur)
        scp = scp_by_id.get(cur)
        if scp is None:
            return False
        cur = _as_id(getattr(scp, "parent_id", ""))
    return False


def _sanitize_parent_links(root, scp_by_id):
    changed = set()
    while True:
        changed_round = False
        for scp in root.af_scp_system.scps:
            sid = _as_id(getattr(scp, "id", ""))
            pid = _as_id(getattr(scp, "parent_id", ""))
            if not pid:
                continue
            if pid == sid or pid not in scp_by_id or _has_cycle_from(sid, scp_by_id):
                _set_prop_raw(scp, "parent_id", "")
                changed.add(sid)
                changed_round = True
        if not changed_round:
            break
        scp_by_id = _scp_map(root)
    return changed, scp_by_id


def _children_map(scp_by_id):
    children = {sid: [] for sid in scp_by_id.keys()}
    for sid, scp in scp_by_id.items():
        pid = _as_id(getattr(scp, "parent_id", ""))
        if pid and pid in children and pid != sid:
            children[pid].append(sid)
    for ids in children.values():
        ids.sort()
    return children


def _resolve_roles_from_map(scp_by_id):
    children = _children_map(scp_by_id)
    roles = {}
    visited = set()

    def walk(sid, inherited_source_id="", inherited_axis="X", trail=None):
        sid = _as_id(sid)
        if not sid:
            return
        if trail is None:
            trail = set()
        if sid in trail:
            return

        scp = scp_by_id.get(sid)
        if scp is None:
            return

        own_axis = _as_axis(getattr(scp, "mirror_axis", "X"))
        mirror_children = bool(getattr(scp, "mirror_enabled", False))

        if mirror_children:
            status = STATUS_SOURCE
            source_id = sid
            effective_axis = own_axis
            next_source_id = sid
            next_axis = own_axis
        elif inherited_source_id:
            status = STATUS_TARGET
            source_id = _as_id(inherited_source_id)
            effective_axis = _as_axis(inherited_axis)
            next_source_id = source_id
            next_axis = effective_axis
        else:
            status = STATUS_NONE
            source_id = ""
            effective_axis = own_axis
            next_source_id = ""
            next_axis = own_axis

        roles[sid] = {
            "status": status,
            "source_id": source_id,
            "effective_axis": effective_axis,
        }
        visited.add(sid)

        next_trail = set(trail)
        next_trail.add(sid)
        for cid in children.get(sid, []):
            walk(cid, inherited_source_id=next_source_id, inherited_axis=next_axis, trail=next_trail)

    root_ids = []
    for sid, scp in scp_by_id.items():
        pid = _as_id(getattr(scp, "parent_id", ""))
        if not pid or pid not in scp_by_id:
            root_ids.append(sid)
    root_ids.sort()

    for sid in root_ids:
        walk(sid, inherited_source_id="", inherited_axis="X", trail=set())

    for sid in sorted(scp_by_id.keys()):
        if sid in visited:
            continue
        walk(sid, inherited_source_id="", inherited_axis="X", trail=set())

    return roles


def apply_scp_mirror_roles(root):
    scp_by_id = _scp_map(root)
    changed, scp_by_id = _sanitize_parent_links(root, scp_by_id)
    roles = _resolve_roles_from_map(scp_by_id)

    for scp in root.af_scp_system.scps:
        sid = _as_id(getattr(scp, "id", ""))
        role = roles.get(
            sid,
            {"status": STATUS_NONE, "source_id": "", "effective_axis": _as_axis(getattr(scp, "mirror_axis", "X"))},
        )

        old_status = _as_id(getattr(scp, "mirror_status", STATUS_NONE)) or STATUS_NONE
        old_source = _as_id(getattr(scp, "mirror_source_id", ""))
        old_axis = _as_axis(getattr(scp, "mirror_effective_axis", "X"))

        new_status = _as_id(role.get("status", STATUS_NONE)) or STATUS_NONE
        new_source = _as_id(role.get("source_id", ""))
        new_axis = _as_axis(role.get("effective_axis", "X"))

        if old_status != new_status:
            _set_prop_raw(scp, "mirror_status", new_status)
            changed.add(sid)
        if old_source != new_source:
            _set_prop_raw(scp, "mirror_source_id", new_source)
            changed.add(sid)
        if old_axis != new_axis:
            _set_prop_raw(scp, "mirror_effective_axis", new_axis)
            changed.add(sid)

    return changed
