import json

import numpy as np

from ..draft_skin.warm import _mesh_arrays as _skin_arrays
from ..topology.warm import _face_values, _mesh_arrays as _topology_arrays

try:
    from ...core.warm_start.migration import prepare_legacy_skin, prepare_legacy_topology
except ImportError:
    from core.warm_start.migration import prepare_legacy_skin, prepare_legacy_topology


SKIN_BINDING_ATTRIBUTES = tuple(
    [f"af_skin_bind_{kind}_{index}" for kind in ("source", "triangle", "barycentric", "weight")
     for index in range(4)] + ["af_skin_bind_normal_offset", "af_skin_bind_support", "af_skin_bind_schema"])
TOPOLOGY_BINDING_ATTRIBUTES = ("af_topology_skin_triangle", "af_topology_skin_barycentric",
                               "af_topology_skin_offset", "af_topology_guide_index",
                               "af_topology_guide_row", "af_topology_guide_parameter",
                               "af_topology_bind_schema")


def migration_state(root, scene):
    skin, topology = _outputs(root, scene)
    return {"skin": _needs(skin, SKIN_BINDING_ATTRIBUTES),
            "topology": _needs(topology, TOPOLOGY_BINDING_ATTRIBUTES)}


def prepare_skin(root, scene, capture):
    obj = _output(root, scene, "af_draft_skin")
    vertices, triangles = _skin_arrays(obj)
    collagen = _point(obj.data, "af_skin_collagen", np.float32, 0.0)
    return prepare_legacy_skin(vertices, triangles, collagen, capture, _stats(obj))


def prepare_topology(root, scene, capture):
    obj = _output(root, scene, "af_topology")
    vertices, quads = _topology_arrays(obj)
    regions = _face_or_default(obj.data, "af_topology_region", 0)
    guides = _face_or_default(obj.data, "af_topology_face_guide_index", -1)
    owners = _point_optional(obj.data, "af_topology_owner_scp_index", np.int32)
    lengths = _point_optional(obj.data, "af_topology_target_edge_length", np.float32)
    return prepare_legacy_topology(vertices, quads, regions, guides, capture,
                                   owners, lengths, _stats(obj))


def _outputs(root, scene):
    return (_find(root, scene, "af_draft_skin"), _find(root, scene, "af_topology"))


def _find(root, scene, tag):
    return next((obj for obj in scene.objects if obj.get(tag)
                 and obj.get("af_root_name") == root.name), None)


def _output(root, scene, tag):
    obj = _find(root, scene, tag)
    if obj is None:
        raise ValueError(f"Current root has no {tag.replace('af_', '').replace('_', ' ')}.")
    return obj


def _needs(obj, attributes):
    if obj is None or obj.type != "MESH":
        return False
    return any(obj.data.attributes.get(name) is None for name in attributes)


def _stats(obj):
    key = "af_skin_stats_json" if obj.get("af_draft_skin") else "af_topology_stats_json"
    try:
        return json.loads(obj.get(key, "{}"))
    except (TypeError, ValueError):
        return {}


def _point(mesh, name, dtype, default):
    values = np.full(len(mesh.vertices), default, dtype=dtype)
    attribute = mesh.attributes.get(name)
    if attribute is not None:
        attribute.data.foreach_get("value", values)
    return values


def _point_optional(mesh, name, dtype):
    return None if mesh.attributes.get(name) is None else _point(mesh, name, dtype, 0)


def _face_or_default(mesh, name, default):
    attribute = mesh.attributes.get(name)
    if attribute is None:
        return np.full(len(mesh.polygons), default, dtype=np.int32)
    return _face_values(mesh, name)
