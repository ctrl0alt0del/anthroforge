import json

import numpy as np

from ..draft_skin.warm import _draft_skin, _mesh_arrays as _skin_arrays, _read_binding
from ..topology.warm import _face_values, _mesh_arrays as _topology_arrays, _read_bindings, _topology


def current_skin_result(root, scene):
    try:
        from ...core.draft_skin.model import SkinResult, SkinValidationReport
    except ImportError:
        from core.draft_skin.model import SkinResult, SkinValidationReport
    try:
        obj = _draft_skin(root, scene)
    except ValueError:
        return None
    vertices, triangles = _skin_arrays(obj)
    collagen = _point_values(obj.data, "af_skin_collagen", np.float32)
    report = SkinValidationReport(True, True, True, True, True, True, True, True)
    return SkinResult(vertices, triangles, collagen, _stats(obj, "af_skin_stats_json"), report,
                      _read_binding(obj.data))


def current_topology_result(root, scene):
    TopologyResult, report = _topology_contract()
    try:
        obj = _topology(root, scene)
    except ValueError:
        return None
    vertices, quads = _topology_arrays(obj); skin, guide = _read_bindings(obj.data)
    return TopologyResult(vertices, quads, _face_values(obj.data, "af_topology_region"),
                          _face_values(obj.data, "af_topology_face_guide_index"),
                          _stats(obj, "af_topology_stats_json"), report,
                          _optional(obj.data, "af_topology_owner_scp_index", np.int32),
                          _optional(obj.data, "af_topology_target_edge_length", np.float32), skin, guide)


def _topology_contract():
    try:
        from ...core.topology.model import TopologyResult, TopologyValidationReport
    except ImportError:
        from core.topology.model import TopologyResult, TopologyValidationReport
    report = TopologyValidationReport(True, True, True, True, True, True, True,
                                      True, True, True, True, True)
    return TopologyResult, report


def _point_values(mesh, name, dtype):
    values = np.zeros(len(mesh.vertices), dtype=dtype)
    attribute = mesh.attributes.get(name)
    if attribute is not None:
        attribute.data.foreach_get("value", values)
    return values


def _optional(mesh, name, dtype):
    attribute = mesh.attributes.get(name)
    if attribute is None:
        return None
    values = np.empty(len(mesh.vertices), dtype=dtype)
    attribute.data.foreach_get("value", values)
    return values


def _stats(obj, key):
    try:
        return json.loads(obj.get(key, "{}"))
    except (TypeError, ValueError):
        return {}
