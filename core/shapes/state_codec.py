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
    if scp_prop is None:
        return False
    raw = str(getattr(scp_prop, "af_deformer_state_json", "") or "").strip()
    if raw:
        return False

    st = str(getattr(scp_prop, "shape_type", "") or "")
    changed = False
    if st == "PARALLELEPIPED":
        changed |= set_deformer_param_patch(scp_prop, "parallelepiped_bend", "enabled", bool(getattr(scp_prop, "parallelepiped_bend_enabled", False)))
        changed |= set_deformer_param_patch(scp_prop, "parallelepiped_bend", "axis", str(getattr(scp_prop, "parallelepiped_bend_axis", "X")))
        changed |= set_deformer_param_patch(scp_prop, "parallelepiped_bend", "angle_deg", float(getattr(scp_prop, "parallelepiped_bend_angle_deg", 0.0)))
        changed |= set_deformer_param_patch(scp_prop, "parallelepiped_bend", "radius", float(getattr(scp_prop, "parallelepiped_bend_radius", 1.0)))
    elif st == "ELLIPSOID":
        changed |= set_deformer_param_patch(scp_prop, "ellipsoid_clip", "enabled", bool(getattr(scp_prop, "ellipsoid_clip_enabled", False)))
        changed |= set_deformer_param_patch(scp_prop, "ellipsoid_clip", "clip1_enabled", bool(getattr(scp_prop, "ellipsoid_clip1_enabled", False)))
        changed |= set_deformer_param_patch(scp_prop, "ellipsoid_clip", "clip1_normal", tuple(getattr(scp_prop, "ellipsoid_clip1_normal", (1.0, 0.0, 0.0))))
        changed |= set_deformer_param_patch(scp_prop, "ellipsoid_clip", "clip1_offset", float(getattr(scp_prop, "ellipsoid_clip1_offset", 0.0)))
        changed |= set_deformer_param_patch(scp_prop, "ellipsoid_clip", "clip1_keep_side", str(getattr(scp_prop, "ellipsoid_clip1_keep_side", "POS")))
        changed |= set_deformer_param_patch(scp_prop, "ellipsoid_clip", "clip2_enabled", bool(getattr(scp_prop, "ellipsoid_clip2_enabled", False)))
        changed |= set_deformer_param_patch(scp_prop, "ellipsoid_clip", "clip2_normal", tuple(getattr(scp_prop, "ellipsoid_clip2_normal", (-1.0, 0.0, 0.0))))
        changed |= set_deformer_param_patch(scp_prop, "ellipsoid_clip", "clip2_offset", float(getattr(scp_prop, "ellipsoid_clip2_offset", 0.0)))
        changed |= set_deformer_param_patch(scp_prop, "ellipsoid_clip", "clip2_keep_side", str(getattr(scp_prop, "ellipsoid_clip2_keep_side", "POS")))
    return bool(changed)


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
