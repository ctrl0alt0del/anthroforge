ASPECT_POSITION = "POSITION"
ASPECT_ROTATION = "ROTATION"


def _normalize_aspects(aspects, default_aspects):
    vals = [str(v or "").strip().upper() for v in (aspects or [])]
    out = [v for v in vals if v in {ASPECT_POSITION, ASPECT_ROTATION}]
    if not out:
        out = list(default_aspects or [ASPECT_POSITION, ASPECT_ROTATION])
    return tuple(dict.fromkeys(out))


def default_behavior_for_mode(mode):
    mode = str(mode or "")
    if mode == "mesh_anchor":
        return {"id": "mesh_anchor", "aspects": [ASPECT_POSITION]}
    return {"id": "surface_follow", "aspects": [ASPECT_POSITION, ASPECT_ROTATION]}


def normalize_behavior(mode, behavior):
    base = default_behavior_for_mode(mode)
    data = dict(base)
    data.update(dict(behavior or {}))
    data["id"] = str(data.get("id") or base["id"])
    data["aspects"] = list(_normalize_aspects(data.get("aspects"), base["aspects"]))
    return data
