_ACTIVE = {}
_SUPPRESSED = set()


def begin_override_session(target_scp_id, parent_mode, child_mode, follow_rotation_mode="KEEP", rotation_strategy="KEEP"):
    begin_override_sessions({str(target_scp_id or ""): (parent_mode, child_mode, follow_rotation_mode, rotation_strategy)})


def begin_override_sessions(values_by_scp_id):
    _ACTIVE.clear()
    _ACTIVE.update(_session_values(values_by_scp_id))


def _session_values(values_by_scp_id):
    return {sid: _session_entry(values) for sid, values in _session_items(values_by_scp_id)}


def _session_items(values_by_scp_id):
    items = dict(values_by_scp_id or {}).items()
    return [(str(sid or ""), values) for sid, values in items if str(sid or "")]


def _session_entry(values):
    data = tuple(values or ())
    keys = ("parent_mode", "child_mode", "follow_rotation_mode", "rotation_strategy")
    return {key: _session_value(data, index) for index, key in enumerate(keys)}


def _session_value(data, index):
    return str(data[index] if index < len(data) else "KEEP")


def clear_override_session():
    _ACTIVE.clear()


def active_parent_override(child_scp):
    return _active_mode(child_scp, "parent_mode")


def active_child_override(child_scp):
    return _active_mode(child_scp, "child_mode")


def active_follow_rotation_override(child_scp):
    mode = _active_mode(child_scp, "follow_rotation_mode")
    return None if not mode else mode == "ENABLED"


def active_rotation_strategy_override(child_scp):
    return _active_mode(child_scp, "rotation_strategy")


def _active_mode(child_scp, key):
    mode = str(_active_entry(child_scp).get(key, "") or "")
    return "" if mode == "KEEP" else mode


def _active_entry(child_scp):
    sid = str(getattr(child_scp, "id", "") or "")
    return dict(_ACTIVE.get(sid, {}) or {})


def suppress_next_depsgraph_ids(ids):
    _SUPPRESSED.update({str(value or "") for value in set(ids or set()) if str(value or "")})


def consume_suppressed_ids(ids):
    valid = {str(value or "") for value in set(ids or set()) if str(value or "")}
    hits = valid & _SUPPRESSED
    _SUPPRESSED.difference_update(hits)
    return valid - hits
