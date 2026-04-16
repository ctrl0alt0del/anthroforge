import json


def _axis_from_use_axis(use_axis):
    try:
        x, y, z = bool(use_axis[0]), bool(use_axis[1]), bool(use_axis[2])
    except Exception:
        x, y, z = True, False, False
    if y and not x and not z:
        return "Y"
    if z and not x and not y:
        return "Z"
    return "X"


def mirror_modifier_state(obj):
    """
    Normalized mirror modifier state for an SCP proxy object.
    """
    mod = None
    try:
        mod = obj.modifiers.get("AF_MIRROR_SOURCE")
    except Exception:
        mod = None

    if mod is None or str(getattr(mod, "type", "") or "") != "MIRROR":
        return {"enabled": False, "axis": "X"}

    axis = "X"
    if hasattr(mod, "use_axis"):
        axis = _axis_from_use_axis(mod.use_axis)
    return {"enabled": True, "axis": str(axis or "X")}


def scp_modifier_state(obj):
    return {"mirror_source": mirror_modifier_state(obj)}


def modifier_state_fingerprint(state):
    try:
        return json.dumps(dict(state or {}), sort_keys=True, separators=(",", ":"))
    except Exception:
        return repr(state)


def geometry_fingerprint(obj):
    """
    Cheap topology/extent fingerprint for proxy geometry change detection.
    """
    if obj is None:
        return ""
    if str(getattr(obj, "type", "") or "") == "MESH" and getattr(obj, "data", None) is not None:
        mesh = obj.data
        v = int(len(getattr(mesh, "vertices", [])))
        e = int(len(getattr(mesh, "edges", [])))
        f = int(len(getattr(mesh, "polygons", [])))
        try:
            bb = tuple(tuple(float(c) for c in p) for p in obj.bound_box)
        except Exception:
            bb = ()
        return f"M:{v}:{e}:{f}:{bb}"
    if str(getattr(obj, "type", "") or "") == "CURVE" and getattr(obj, "data", None) is not None:
        curve = obj.data
        splines = getattr(curve, "splines", [])
        parts = []
        for s in splines:
            st = str(getattr(s, "type", "") or "")
            if st == "BEZIER":
                n = int(len(getattr(s, "bezier_points", [])))
            else:
                n = int(len(getattr(s, "points", [])))
            parts.append((st, n, bool(getattr(s, "use_cyclic_u", False))))
        return f"C:{tuple(parts)}"
    return ""
