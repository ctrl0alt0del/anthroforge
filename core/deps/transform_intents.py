from collections import defaultdict
from mathutils import Matrix


_SCP_TRANSFORM_INTENTS = defaultdict(list)


def _root_key(root):
    return str(getattr(root, "name", "") or "")


def enqueue_scp_transform_intent(root, scp_id, matrix_world):
    if root is None or not scp_id or matrix_world is None:
        return False
    key = _root_key(root)
    if not key:
        return False
    _SCP_TRANSFORM_INTENTS[key].append((str(scp_id), [list(r) for r in matrix_world]))
    return True


def pop_scp_transform_intents(root):
    key = _root_key(root)
    if not key:
        return []
    raw = _SCP_TRANSFORM_INTENTS.pop(key, [])
    # Keep only the latest intent per SCP id to avoid replaying stale transforms.
    latest_by_id = {}
    for scp_id, rows in raw:
        sid = str(scp_id)
        if sid in latest_by_id:
            latest_by_id.pop(sid, None)
        latest_by_id[sid] = rows

    out = []
    for scp_id, rows in latest_by_id.items():
        try:
            mw = Matrix(rows)
        except Exception:
            continue
        out.append((str(scp_id), mw))
    return out
