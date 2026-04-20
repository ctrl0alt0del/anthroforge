from collections import defaultdict
import time
import uuid
from mathutils import Matrix


_SCP_TRANSFORM_INTENTS = defaultdict(list)


def _root_key(root):
    return str(getattr(root, "name", "") or "")


def enqueue_scp_transform_intent(root, scp_id, matrix_world, *, source="unknown", payload=None, txn_id=None):
    if root is None or not scp_id or matrix_world is None:
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
    _SCP_TRANSFORM_INTENTS[key].append((str(scp_id), [list(r) for r in matrix_world], meta))
    return True


def pop_scp_transform_intents(root):
    key = _root_key(root)
    if not key:
        return []
    raw = _SCP_TRANSFORM_INTENTS.pop(key, [])
    # Keep only the latest intent per SCP id to avoid replaying stale transforms.
    latest_by_id = {}
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        scp_id = item[0]
        rows = item[1]
        meta = dict(item[2] or {}) if len(item) >= 3 and isinstance(item[2], dict) else {}
        sid = str(scp_id)
        if sid in latest_by_id:
            latest_by_id.pop(sid, None)
        latest_by_id[sid] = (rows, meta)

    out = []
    for scp_id, item in latest_by_id.items():
        rows, meta = item
        try:
            mw = Matrix(rows)
        except Exception:
            continue
        out.append((str(scp_id), mw, dict(meta or {})))
    return out
