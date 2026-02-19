import json


def _read_map(scene):
    raw = (scene.af_tree_collapsed_json or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_map(scene, data):
    scene.af_tree_collapsed_json = json.dumps(data)


def is_collapsed(scene, scp_id):
    data = _read_map(scene)
    return bool(data.get(scp_id, False))


def set_collapsed(scene, scp_id, value):
    data = _read_map(scene)
    data[scp_id] = bool(value)
    _write_map(scene, data)


def toggle_collapsed(scene, scp_id):
    data = _read_map(scene)
    data[scp_id] = not bool(data.get(scp_id, False))
    _write_map(scene, data)
    return data[scp_id]
