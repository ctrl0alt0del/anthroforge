from .conflict_resolver import resolve_conflict


def _get_scp_prop(root, scp_id):
    sid = str(scp_id or "")
    if root is None or not sid:
        return None
    for scp in root.af_scp_system.scps:
        if str(getattr(scp, "id", "") or "") == sid:
            return scp
    return None


def _apply_mirror_source_state(scp_prop, state, *, source="unknown", payload=None):
    changed = False
    sid = str(getattr(scp_prop, "id", "") or "")
    enabled = bool(dict(state or {}).get("enabled", False))
    axis = str(dict(state or {}).get("axis", "X") or "X").upper()
    if axis not in ("X", "Y", "Z"):
        axis = "X"

    cur_enabled = bool(getattr(scp_prop, "mirror_enabled", False))
    next_enabled = bool(
        resolve_conflict(
            entity_type="SCP",
            entity_id=sid,
            aspect="mirror.enabled",
            source=source,
            current=cur_enabled,
            incoming=enabled,
            payload=payload,
        )
    )
    if cur_enabled != next_enabled:
        scp_prop.mirror_enabled = next_enabled
        changed = True

    cur_axis = str(getattr(scp_prop, "mirror_axis", "X") or "X").upper()
    next_axis = str(
        resolve_conflict(
            entity_type="SCP",
            entity_id=sid,
            aspect="mirror.axis",
            source=source,
            current=cur_axis,
            incoming=axis,
            payload=payload,
        )
        or "X"
    ).upper()
    if next_axis not in ("X", "Y", "Z"):
        next_axis = "X"
    if cur_axis != next_axis:
        scp_prop.mirror_axis = next_axis
        changed = True
    return changed


def apply_scp_modifier_intent(root, scp_id, state, *, source="unknown", payload=None):
    scp_prop = _get_scp_prop(root, scp_id)
    if scp_prop is None:
        return False
    state_payload = dict(state or {})
    meta_payload = dict(payload or {})
    changed = False
    if "mirror_source" in state_payload:
        changed |= _apply_mirror_source_state(
            scp_prop,
            state_payload.get("mirror_source", {}),
            source=source,
            payload=meta_payload,
        )
    return changed
