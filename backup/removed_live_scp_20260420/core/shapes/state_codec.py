import json


def _parse_state_json(raw):
    txt = str(raw or "").strip()
    if not txt:
        return {}
    try:
        data = json.loads(txt)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def get_deformer_param_overrides(scp_prop):
    data = _parse_state_json(getattr(scp_prop, "af_deformer_state_json", ""))
    deformers = data.get("deformers", {})
    if not isinstance(deformers, dict):
        return {}
    out = {}
    for did, body in deformers.items():
        if not isinstance(body, dict):
            continue
        params = body.get("params", {})
        if not isinstance(params, dict):
            continue
        out[str(did)] = dict(params)
    return out


def ensure_deformer_state_seeded(scp_prop):
    _ = scp_prop
    return False


def set_deformer_param_patch(scp_prop, deformer_id, key, value):
    data = _parse_state_json(getattr(scp_prop, "af_deformer_state_json", ""))
    deformers = data.setdefault("deformers", {})
    if not isinstance(deformers, dict):
        deformers = {}
        data["deformers"] = deformers
    did = str(deformer_id or "")
    if not did:
        return False
    body = deformers.setdefault(did, {})
    if not isinstance(body, dict):
        body = {}
        deformers[did] = body
    params = body.setdefault("params", {})
    if not isinstance(params, dict):
        params = {}
        body["params"] = params
    k = str(key or "")
    if not k:
        return False
    if params.get(k) == value:
        return False
    params[k] = value
    scp_prop.af_deformer_state_json = json.dumps(data, separators=(",", ":"))
    return True
