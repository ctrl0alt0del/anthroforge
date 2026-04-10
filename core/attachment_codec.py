import json
from mathutils import Vector

from .effects import (
    ASPECT_POSITION,
    ASPECT_ROTATION,
    default_behavior_for_mode,
    normalize_behavior,
)


def _vec3(value, fallback):
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return Vector((float(value[0]), float(value[1]), float(value[2])))
    return fallback.copy()


def _default_surface_frame_payload():
    return {
        "parent_param": 0.0,
        "child_origin_local": Vector((0.0, 0.0, 0.0)),
        "child_tangent_local": Vector((1.0, 0.0, 0.0)),
        "child_normal_local": Vector((0.0, 0.0, 1.0)),
    }


def _surface_frame_from_data(data):
    payload = _default_surface_frame_payload()
    payload["parent_param"] = data.get("parent_param", 0.0)
    payload["child_origin_local"] = _vec3(data.get("child_origin_local"), payload["child_origin_local"])
    payload["child_tangent_local"] = _vec3(data.get("child_tangent_local"), payload["child_tangent_local"])
    payload["child_normal_local"] = _vec3(data.get("child_normal_local"), payload["child_normal_local"])
    return "surface_frame_v1", payload


def _mesh_anchor_from_data(data):
    p = data.get("parent_local_point")
    c = data.get("child_local_point")
    if isinstance(p, (list, tuple)) and len(p) == 3 and isinstance(c, (list, tuple)) and len(c) == 3:
        return "mesh_anchor", (Vector((float(p[0]), float(p[1]), float(p[2]))), Vector((float(c[0]), float(c[1]), float(c[2]))))
    if isinstance(p, (list, tuple)) and len(p) == 3:
        return "mesh_anchor", (Vector((float(p[0]), float(p[1]), float(p[2]))), Vector((0.0, 0.0, 0.0)))
    return None


def _parse_behavior(mode, data):
    if not isinstance(data, dict):
        return default_behavior_for_mode(mode)
    raw = data.get("behavior", None)
    if not isinstance(raw, dict):
        return default_behavior_for_mode(mode)
    return normalize_behavior(mode, raw)


def parse_scp_attach_descriptor(raw):
    raw = (raw or "").strip()
    if not raw:
        mode = "surface_frame_v1"
        payload = _default_surface_frame_payload()
        return mode, payload, default_behavior_for_mode(mode)

    try:
        data = json.loads(raw)
    except Exception:
        data = {}

    if isinstance(data, dict) and data.get("mode") == "surface_frame_v1":
        mode, payload = _surface_frame_from_data(data)
        return mode, payload, _parse_behavior(mode, data)
    if isinstance(data, dict) and data.get("mode") == "mesh_anchor":
        parsed = _mesh_anchor_from_data(data)
        if parsed is not None:
            mode, payload = parsed
            return mode, payload, _parse_behavior(mode, data)

    mode = "surface_frame_v1"
    payload = _default_surface_frame_payload()
    return mode, payload, default_behavior_for_mode(mode)


def parse_scp_attach_param(raw):
    mode, payload, _behavior = parse_scp_attach_descriptor(raw)
    return mode, payload


def encode_surface_frame(parent_param, child_origin_local, child_tangent_local, child_normal_local, behavior=None):
    behavior_n = normalize_behavior("surface_frame_v1", behavior or default_behavior_for_mode("surface_frame_v1"))
    return json.dumps(
        {
            "mode": "surface_frame_v1",
            "parent_param": parent_param,
            "child_origin_local": [float(child_origin_local.x), float(child_origin_local.y), float(child_origin_local.z)],
            "child_tangent_local": [float(child_tangent_local.x), float(child_tangent_local.y), float(child_tangent_local.z)],
            "child_normal_local": [float(child_normal_local.x), float(child_normal_local.y), float(child_normal_local.z)],
            "behavior": {
                "id": str(behavior_n.get("id", "surface_follow")),
                "aspects": [str(v) for v in behavior_n.get("aspects", [ASPECT_POSITION, ASPECT_ROTATION])],
            },
        }
    )


def encode_scp_mesh_anchor(parent_local_point, child_local_point, behavior=None):
    behavior_n = normalize_behavior("mesh_anchor", behavior or default_behavior_for_mode("mesh_anchor"))
    return json.dumps(
        {
            "mode": "mesh_anchor",
            "parent_local_point": [
                float(parent_local_point.x),
                float(parent_local_point.y),
                float(parent_local_point.z),
            ],
            "child_local_point": [
                float(child_local_point.x),
                float(child_local_point.y),
                float(child_local_point.z),
            ],
            "behavior": {
                "id": str(behavior_n.get("id", "mesh_anchor")),
                "aspects": [str(v) for v in behavior_n.get("aspects", [ASPECT_POSITION])],
            },
        }
    )


def parse_fiber_attach_param(raw):
    raw = (raw or "").strip()
    if not raw:
        return ("shape_param_v1", 0.0)

    try:
        data = json.loads(raw)
    except Exception:
        data = {}

    if isinstance(data, dict) and data.get("mode") == "shape_param_v1":
        return ("shape_param_v1", data.get("parent_param", 0.0))

    if isinstance(data, dict) and data.get("mode") == "mesh_anchor":
        p = data.get("parent_local_point")
        if isinstance(p, (list, tuple)) and len(p) == 3:
            return ("mesh_anchor", Vector((float(p[0]), float(p[1]), float(p[2]))))

    return ("shape_param_v1", 0.0)


def encode_fiber_shape_param(parent_param):
    return json.dumps({"mode": "shape_param_v1", "parent_param": parent_param})


def encode_fiber_mesh_anchor(parent_local_point):
    return json.dumps(
        {
            "mode": "mesh_anchor",
            "parent_local_point": [
                float(parent_local_point.x),
                float(parent_local_point.y),
                float(parent_local_point.z),
            ],
        }
    )
