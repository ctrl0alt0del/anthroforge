from collections import defaultdict
import time
import uuid


_SCP_MODIFIER_INTENTS = defaultdict(list)


def _root_key(root):
    return str(getattr(root, "name", "") or "")


def enqueue_scp_modifier_intent(root, scp_id, state, *, source="unknown", payload=None, txn_id=None):
    sid = str(scp_id or "")
    if root is None or not sid:
        return False
    key = _root_key(root)
    if not key:
        return False
    meta = {
        "source": str(source or "unknown"),
        "payload": dict(payload or {}),
        "txn_id": str(txn_id or uuid.uuid4()),
        "ts": float(time.time()),
    }
    _SCP_MODIFIER_INTENTS[key].append((sid, dict(state or {}), meta))
    return True


def pop_scp_modifier_intents(root):
    key = _root_key(root)
    if not key:
        return []
    raw = _SCP_MODIFIER_INTENTS.pop(key, [])
    latest = {}
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        sid = str(item[0] or "")
        state = dict(item[1] or {})
        meta = dict(item[2] or {}) if len(item) >= 3 and isinstance(item[2], dict) else {}
        latest.pop(sid, None)
        latest[sid] = (state, meta)
    out = []
    for sid, item in latest.items():
        state, meta = item
        out.append((sid, dict(state or {}), dict(meta or {})))
    return out
