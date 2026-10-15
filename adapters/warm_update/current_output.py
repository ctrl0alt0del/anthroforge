from ..mesh_issues import restore_report
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
    report = restore_report(_stats(obj, "af_skin_stats_json"), SkinValidationReport)
    return SkinResult(vertices, triangles, collagen, _stats(obj, "af_skin_stats_json"), report,
                      _optional_binding(obj.data))


def current_topology_result(root, scene, obj=None):
    TopologyResult, report_type = _topology_contract()
    try:
        obj = obj if obj is not None else _topology(root, scene)
    except ValueError:
        return None
    vertices, quads = _topology_arrays(obj); skin, guide = _optional_topology_bindings(obj.data)
    report = restore_report(_stats(obj, "af_topology_stats_json"), report_type)
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
    return TopologyResult, TopologyValidationReport


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


def bound_skin_result(root, scene):
    from types import SimpleNamespace
    try:
        from ...core.draft_skin.model import SkinResult, SkinValidationReport
    except ImportError:
        from core.draft_skin.model import SkinResult, SkinValidationReport
    obj = _topology(root, scene)
    mesh = obj.get("af_bound_skin")
    if mesh is None:
        return current_skin_result(root, scene)
    vertices, faces = _skin_arrays(SimpleNamespace(data=mesh))
    stats = json.loads(mesh.get("af_result_stats_json", "{}"))
    return SkinResult(vertices, faces, _point_values(mesh, "af_skin_collagen", np.float32), stats,
                      restore_report(stats, SkinValidationReport), _optional_binding(mesh))


def _optional_binding(mesh):
    try:
        return _read_binding(mesh)
    except ValueError:
        return None


def _optional_topology_bindings(mesh):
    try:
        return _read_bindings(mesh)
    except ValueError:
        return None, None
