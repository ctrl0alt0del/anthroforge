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


def _default_scp_attach():
    mode = "surface_frame_v1"
    return mode, _default_surface_frame_payload(), default_behavior_for_mode(mode)


def _scp_attach_from_data(data):
    mode = "" if not isinstance(data, dict) else data.get("mode")
    if mode == "surface_frame_v1":
        parsed = _surface_frame_from_data(data)
    elif mode == "mesh_anchor":
        parsed = _mesh_anchor_from_data(data)
    else:
        parsed = None
    if parsed is None:
        return None
    name, payload = parsed
    return name, payload, _parse_behavior(name, data)


def parse_scp_attach_descriptor(raw):
    raw = (raw or "").strip()
    if not raw:
        return _default_scp_attach()
    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    return _scp_attach_from_data(data) or _default_scp_attach()


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


def _vec_list(value):
    return [float(value.x), float(value.y), float(value.z)]


def _behavior_payload(behavior_n, default_id, default_aspects):
    return {
        "id": str(behavior_n.get("id", default_id)),
        "aspects": [str(v) for v in behavior_n.get("aspects", default_aspects)],
    }


def encode_scp_mesh_anchor(parent_local_point, child_local_point, behavior=None):
    behavior_n = normalize_behavior("mesh_anchor", behavior or default_behavior_for_mode("mesh_anchor"))
    return json.dumps(
        {
            "mode": "mesh_anchor",
            "parent_local_point": _vec_list(parent_local_point),
            "child_local_point": _vec_list(child_local_point),
            "behavior": _behavior_payload(behavior_n, "mesh_anchor", [ASPECT_POSITION]),
        }
    )


def parse_fiber_attach_param(raw):
    raw = (raw or "").strip()
    if not raw:
        return "shape_param_v1", 0.0
    return _fiber_mode_payload(_json_data(raw))


def fiber_attach_mode(raw):
    return parse_fiber_attach_param(raw)[0]


def is_fiber_vertex_attach(raw):
    return fiber_attach_mode(raw) == "mesh_vertex_v1"


def fiber_attach_signature(raw):
    data = _json_data(raw)
    return "" if not isinstance(data, dict) else str(data.get("topology_signature", "") or "")


def _fiber_mode_payload(data):
    mode = "" if not isinstance(data, dict) else str(data.get("mode", "") or "")
    if mode == "shape_param_v1":
        return "shape_param_v1", data.get("parent_param", 0.0)
    if mode == "mesh_anchor":
        return _fiber_mesh_anchor(data)
    if mode == "mesh_vertex_v1":
        return "mesh_vertex_v1", int(data.get("vertex_index", -1))
    return "shape_param_v1", 0.0


def _fiber_mesh_anchor(data):
    p = data.get("parent_local_point")
    return ("mesh_anchor", Vector((float(p[0]), float(p[1]), float(p[2])))) if isinstance(p, (list, tuple)) and len(p) == 3 else ("shape_param_v1", 0.0)


def _json_data(raw):
    try:
        return json.loads(raw)
    except Exception:
        return {}


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


def encode_fiber_vertex_index(vertex_index, topology_signature=""):
    return json.dumps({"mode": "mesh_vertex_v1", "vertex_index": int(vertex_index), "topology_signature": str(topology_signature or "")})
