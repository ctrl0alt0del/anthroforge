from collections import OrderedDict
from dataclasses import dataclass

try:
    from ..control_flags import is_control_object, set_control_flag_keys
except ImportError:
    from core.control_flags import is_control_object, set_control_flag_keys
from .runtime_intents import enqueue_runtime_intent


@dataclass(frozen=True)
class ControlBinding:
    kind: str
    space: str
    target_path: str
    metadata: dict | None = None


@dataclass(frozen=True)
class ControlDescriptor:
    flag_key: str
    control_type: str
    build_info: object


_CONTROL_DESCRIPTORS = OrderedDict()


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


def _as_id(value):
    return str(value or "").strip()


def _as_index(obj, key):
    try:
        return int(obj.get(key, -1))
    except Exception:
        return -1


def _binding(kind, space, target_path):
    return ControlBinding(kind=kind, space=space, target_path=target_path)


def _info(control_type, entity_type, entity_id, root_name, obj_name, payload, binding):
    return {
        "control_type": control_type,
        "payload": {"root_name": root_name, "object_name": obj_name, **dict(payload or {})},
        "dirty_hints": {entity_type: {entity_id}},
        "binding": binding,
    }


def _refresh_flag_keys():
    set_control_flag_keys(tuple(desc.flag_key for desc in _CONTROL_DESCRIPTORS.values()))


def register_control_descriptor(descriptor, replace=False):
    key = str(getattr(descriptor, "control_type", "") or "").strip()
    if not key:
        raise ValueError("descriptor.control_type is required")
    if key in _CONTROL_DESCRIPTORS and not replace:
        raise ValueError(f"control descriptor already registered: {key}")
    _CONTROL_DESCRIPTORS[key] = descriptor
    _refresh_flag_keys()


def _descriptor(flag_key, control_type, build_info):
    return ControlDescriptor(str(flag_key or ""), str(control_type or ""), build_info)


def _scp_control_info(obj, root_name):
    sid = _as_id(obj.get("af_scp_id"))
    if not sid:
        return None
    bind = _binding("DEFORMER_CONTROL", "WORLD", f"SCP/{sid}/external_control")
    return _info("SCP_CONTROL_OBJECT", "SCP", sid, root_name, str(obj.name), {"scp_id": sid}, bind)


def _curve_point_info(obj, root_name):
    sid, idx = _as_id(obj.get("af_scp_id")), _as_index(obj, "af_curve_point_index")
    if not sid or idx < 0:
        return None
    bind = _binding("GEOMETRY_SAMPLE", "FINAL", f"SCP/{sid}/curve_points/{idx}")
    return _info("SCP_CURVE_POINT", "SCP", sid, root_name, str(obj.name), {"scp_id": sid, "point_index": idx}, bind)


def _parallelepiped_info(obj, root_name):
    sid, idx = _as_id(obj.get("af_scp_id")), _as_index(obj, "af_parallelepiped_vert_index")
    if not sid or idx < 0:
        return None
    bind = _binding("GEOMETRY_SAMPLE", "FINAL", f"SCP/{sid}/parallelepiped_points/{idx}")
    return _info("SCP_PARALLELEPIPED_VERTEX", "SCP", sid, root_name, str(obj.name), {"scp_id": sid, "vert_index": idx}, bind)


def _fiber_endpoint_info(obj, root_name):
    fid, endpoint = _as_id(obj.get("af_fiber_id")), _as_id(obj.get("af_fiber_endpoint"))
    if not fid or endpoint not in ("A", "B"):
        return None
    bind = _binding("GEOMETRY_SAMPLE", "FINAL", f"FIBER/{fid}/endpoint/{endpoint}")
    return _info("FIBER_ENDPOINT", "FIBER", fid, root_name, str(obj.name), {"fiber_id": fid, "endpoint": endpoint}, bind)


def _fiber_touch_info(obj, root_name):
    fid, idx = _as_id(obj.get("af_fiber_id")), _as_index(obj, "af_fiber_touch_index")
    if not fid or idx < 0:
        return None
    bind = _binding("GEOMETRY_SAMPLE", "FINAL", f"FIBER/{fid}/touch/{idx}")
    return _info("FIBER_TOUCH", "FIBER", fid, root_name, str(obj.name), {"fiber_id": fid, "touch_index": idx}, bind)


def _fiber_loop_anchor_info(obj, root_name):
    fid, idx = _as_id(obj.get("af_fiber_id")), _as_index(obj, "af_fiber_loop_anchor_index")
    if not fid or idx < 0:
        return None
    bind = _binding("GEOMETRY_SAMPLE", "FINAL", f"FIBER/{fid}/loop_anchor/{idx}")
    payload = {"fiber_id": fid, "loop_anchor_index": idx}
    return _info("FIBER_LOOP_ANCHOR", "FIBER", fid, root_name, str(obj.name), payload, bind)


def _muscle_inflation_info(obj, root_name):
    mid = _as_id(obj.get("af_muscle_id"))
    if not mid:
        return None
    bind = _binding("GEOMETRY_SAMPLE", "FINAL", f"MUSCLE/{mid}/inflation_ctrl")
    return _info("MUSCLE_INFLATION", "MUSCLE", mid, root_name, str(obj.name), {"muscle_id": mid}, bind)


def _blob_control_info(obj, root_name):
    bid = _as_id(obj.get("af_blob_id"))
    if not bid:
        return None
    bind = _binding("GEOMETRY_SAMPLE", "FINAL", f"BLOB/{bid}/control_point")
    return _info("BLOB_CONTROL", "BLOB", bid, root_name, str(obj.name), {"blob_id": bid}, bind)


def _builtin_descriptors():
    data = (
        ("af_scp_control", "SCP_CONTROL_OBJECT", _scp_control_info),
        ("af_curve_point_handle", "SCP_CURVE_POINT", _curve_point_info),
        ("af_parallelepiped_vert_handle", "SCP_PARALLELEPIPED_VERTEX", _parallelepiped_info),
        ("af_fiber_endpoint_handle", "FIBER_ENDPOINT", _fiber_endpoint_info),
        ("af_fiber_touch_handle", "FIBER_TOUCH", _fiber_touch_info),
        ("af_fiber_loop_anchor_handle", "FIBER_LOOP_ANCHOR", _fiber_loop_anchor_info),
        ("af_muscle_inflation_ctrl", "MUSCLE_INFLATION", _muscle_inflation_info),
        ("af_blob_control_gizmo", "BLOB_CONTROL", _blob_control_info),
    )
    return tuple(_descriptor(*item) for item in data)


def register_builtin_control_descriptors():
    for descriptor in _builtin_descriptors():
        register_control_descriptor(descriptor, replace=True)


def _root_name(obj):
    getter = getattr(obj, "get", lambda *_args: None)
    return _as_id(getter("af_root_name"))


def _matching_descriptor(obj):
    for descriptor in _CONTROL_DESCRIPTORS.values():
        try:
            if obj.get(descriptor.flag_key):
                return descriptor
        except Exception:
            continue
    return None


def classify_control_object(obj):
    if obj is None:
        return None
    root_name = _root_name(obj)
    descriptor = _matching_descriptor(obj) if root_name else None
    return None if descriptor is None else descriptor.build_info(obj, root_name)


register_builtin_control_descriptors()
