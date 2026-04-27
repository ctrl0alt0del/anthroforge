from dataclasses import dataclass

from .runtime_intents import enqueue_runtime_intent


@dataclass(frozen=True)
class ControlBinding:
    kind: str
    space: str
    target_path: str
    metadata: dict | None = None


CONTROL_FLAG_KEYS = (
    "af_curve_point_handle",
    "af_parallelepiped_vert_handle",
    "af_fiber_endpoint_handle",
    "af_fiber_touch_handle",
    "af_muscle_inflation_ctrl",
    "af_blob_control_gizmo",
)


class ControlIntent:
    def __init__(self, control_type, payload):
        self.control_type = str(control_type or "")
        self.payload = dict(payload or {})

def _control_entity_id(payload):
    return str(dict(payload or {}).get("object_name", "") or "")


def enqueue_control_intent(root, control_type, payload):
    return enqueue_runtime_intent(
        root=root,
        intent_type=f"CONTROL/{str(control_type or '')}",
        entity_type="CONTROL",
        entity_id=_control_entity_id(payload),
        payload=payload,
        source="depsgraph",
        event_type="TRANSFORM",
    )


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
