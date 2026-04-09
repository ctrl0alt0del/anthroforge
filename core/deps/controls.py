from collections import defaultdict
from ..shapes.state import ControlBinding


CONTROL_FLAG_KEYS = (
    "af_curve_point_handle",
    "af_parallelepiped_vert_handle",
    "af_ellipsoid_clip_handle",
    "af_fiber_endpoint_handle",
    "af_fiber_touch_handle",
    "af_muscle_inflation_ctrl",
    "af_blob_control_gizmo",
)


class ControlIntent:
    def __init__(self, control_type, payload):
        self.control_type = str(control_type or "")
        self.payload = dict(payload or {})


_CONTROL_INTENTS = defaultdict(list)


def _root_key(root):
    return str(getattr(root, "name", "") or "")


def enqueue_control_intent(root, control_type, payload):
    key = _root_key(root)
    if not key:
        return False
    _CONTROL_INTENTS[key].append(ControlIntent(control_type=control_type, payload=payload))
    return True


def pop_control_intents(root):
    key = _root_key(root)
    if not key:
        return []
    return list(_CONTROL_INTENTS.pop(key, []))


def _as_id(v):
    return str(v or "").strip()


def is_control_object(obj):
    if obj is None:
        return False
    for k in CONTROL_FLAG_KEYS:
        try:
            if obj.get(k):
                return True
        except Exception:
            continue
    return False


def classify_control_object(obj):
    if obj is None:
        return None

    root_name = _as_id(getattr(obj, "get", lambda *_: None)("af_root_name"))
    if not root_name:
        return None

    if obj.get("af_curve_point_handle"):
        scp_id = _as_id(obj.get("af_scp_id"))
        idx = int(obj.get("af_curve_point_index", -1))
        if scp_id and idx >= 0:
            return {
                "control_type": "SCP_CURVE_POINT",
                "payload": {"root_name": root_name, "object_name": str(obj.name), "scp_id": scp_id, "point_index": idx},
                "dirty_hints": {"SCP": {scp_id}},
                "binding": ControlBinding(kind="GEOMETRY_SAMPLE", space="FINAL", target_path=f"SCP/{scp_id}/curve_points/{idx}"),
            }
    if obj.get("af_parallelepiped_vert_handle"):
        scp_id = _as_id(obj.get("af_scp_id"))
        idx = int(obj.get("af_parallelepiped_vert_index", -1))
        if scp_id and idx >= 0:
            return {
                "control_type": "SCP_PARALLELEPIPED_VERTEX",
                "payload": {"root_name": root_name, "object_name": str(obj.name), "scp_id": scp_id, "vert_index": idx},
                "dirty_hints": {"SCP": {scp_id}},
                "binding": ControlBinding(kind="GEOMETRY_SAMPLE", space="FINAL", target_path=f"SCP/{scp_id}/parallelepiped_points/{idx}"),
            }
    if obj.get("af_ellipsoid_clip_handle"):
        scp_id = _as_id(obj.get("af_scp_id"))
        idx = int(obj.get("af_ellipsoid_clip_index", -1))
        if scp_id and idx in (1, 2):
            return {
                "control_type": "SCP_ELLIPSOID_CLIP",
                "payload": {"root_name": root_name, "object_name": str(obj.name), "scp_id": scp_id, "clip_index": idx},
                "dirty_hints": {"SCP": {scp_id}},
                "binding": ControlBinding(kind="FRAME_SAMPLE", space="BASE", target_path=f"SCP/{scp_id}/ellipsoid_clip{idx}"),
            }
    if obj.get("af_fiber_endpoint_handle"):
        fid = _as_id(obj.get("af_fiber_id"))
        endpoint = _as_id(obj.get("af_fiber_endpoint"))
        if fid and endpoint in ("A", "B"):
            return {
                "control_type": "FIBER_ENDPOINT",
                "payload": {"root_name": root_name, "object_name": str(obj.name), "fiber_id": fid, "endpoint": endpoint},
                "dirty_hints": {"FIBER": {fid}},
                "binding": ControlBinding(kind="GEOMETRY_SAMPLE", space="FINAL", target_path=f"FIBER/{fid}/endpoint/{endpoint}"),
            }
    if obj.get("af_fiber_touch_handle"):
        fid = _as_id(obj.get("af_fiber_id"))
        idx = int(obj.get("af_fiber_touch_index", -1))
        if fid and idx >= 0:
            return {
                "control_type": "FIBER_TOUCH",
                "payload": {"root_name": root_name, "object_name": str(obj.name), "fiber_id": fid, "touch_index": idx},
                "dirty_hints": {"FIBER": {fid}},
                "binding": ControlBinding(kind="GEOMETRY_SAMPLE", space="FINAL", target_path=f"FIBER/{fid}/touch/{idx}"),
            }
    if obj.get("af_muscle_inflation_ctrl"):
        mid = _as_id(obj.get("af_muscle_id"))
        if mid:
            return {
                "control_type": "MUSCLE_INFLATION",
                "payload": {"root_name": root_name, "object_name": str(obj.name), "muscle_id": mid},
                "dirty_hints": {"MUSCLE": {mid}},
                "binding": ControlBinding(kind="GEOMETRY_SAMPLE", space="FINAL", target_path=f"MUSCLE/{mid}/inflation_ctrl"),
            }
    if obj.get("af_blob_control_gizmo"):
        bid = _as_id(obj.get("af_blob_id"))
        if bid:
            return {
                "control_type": "BLOB_CONTROL",
                "payload": {"root_name": root_name, "object_name": str(obj.name), "blob_id": bid},
                "dirty_hints": {"BLOB": {bid}},
                "binding": ControlBinding(kind="GEOMETRY_SAMPLE", space="FINAL", target_path=f"BLOB/{bid}/control_point"),
            }
    return None
