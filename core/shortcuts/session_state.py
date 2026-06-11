_ACTIVE = {}
_SUPPRESSED = set()


def begin_override_session(target_scp_id, parent_mode, child_mode):
    _ACTIVE.clear()
    _ACTIVE.update({"target_scp_id": str(target_scp_id or ""), "parent_mode": str(parent_mode or "KEEP"), "child_mode": str(child_mode or "KEEP")})


def clear_override_session():
    _ACTIVE.clear()


def active_parent_override(child_scp):
    return _active_mode(child_scp, "parent_mode")


def active_child_override(child_scp):
    return _active_mode(child_scp, "child_mode")


def _active_mode(child_scp, key):
    same = str(getattr(child_scp, "id", "")) == str(_ACTIVE.get("target_scp_id", ""))
    mode = str(_ACTIVE.get(key, "") or "")
    return "" if not same or mode == "KEEP" else mode


def suppress_next_depsgraph_ids(ids):
    _SUPPRESSED.update({str(value or "") for value in set(ids or set()) if str(value or "")})


def consume_suppressed_ids(ids):
    valid = {str(value or "") for value in set(ids or set()) if str(value or "")}
    hits = valid & _SUPPRESSED
    _SUPPRESSED.difference_update(hits)
    return valid - hits
