import json

import numpy as np

from .capture import capture_topology

try:
    from ...core.topology.model import TopologyGuide
    from ...core.warm_start.model import (
        TopologyGuideBinding, TopologySkinBinding, WarmInvalidationReason,
        WarmUpdateStatus, WarmValidationReport,
    )
    from ...core.warm_start.signatures import guide_layout_signature
    from ...core.warm_start.topology_solver import project_and_rebind_topology, reproject_topology
except ImportError:
    from core.topology.model import TopologyGuide
    from core.warm_start.model import (
        TopologyGuideBinding, TopologySkinBinding, WarmInvalidationReason,
        WarmUpdateStatus, WarmValidationReport,
    )
    from core.warm_start.signatures import guide_layout_signature
    from core.warm_start.topology_solver import project_and_rebind_topology, reproject_topology


def update_topology(root, scene, depsgraph, capture=None):
    obj = _topology(root, scene)
    vertices, quads = _mesh_arrays(obj)
    skin_binding, guide_binding = _read_bindings(obj.data)
    capture = capture or capture_topology(root, scene, depsgraph)
    old_guides = _stored_guides(obj)
    new_guides = _current_patch_guides(obj, capture.guides)
    if not _valid_guide_layout(obj, new_guides):
        return _guide_fallback(vertices)
    result = reproject_topology(vertices, quads, capture.vertices, capture.triangles,
                                skin_binding, guide_binding, old_guides, new_guides,
                                symmetry_plane=capture.plane)
    if result[1].valid:
        apply_topology_vertices(obj, result[0])
    return result


def _valid_guide_layout(obj, guides):
    stats = json.loads(obj.get("af_topology_stats_json", "{}"))
    expected = stats.get("guide_layout_signature", "")
    return not expected or expected == guide_layout_signature(guides)


def _guide_fallback(vertices):
    message = "Topology warm start invalidated because guide layout changed."
    status = WarmUpdateStatus(False, "Fallback", 1.0, message,
                              WarmInvalidationReason.GUIDE_LAYOUT_CHANGED)
    report = WarmValidationReport(False, True, True, True, 0.0, 0.0, message)
    return vertices, status, report


def rebind_after_skin(root, scene, depsgraph, predicted=None, capture=None):
    obj = _topology(root, scene)
    vertices, quads = _mesh_arrays(obj)
    capture = capture or capture_topology(root, scene, depsgraph)
    regions = _face_values(obj.data, "af_topology_region")
    guides = _face_values(obj.data, "af_topology_face_guide_index")
    patch_guides = _current_patch_guides(obj, capture.guides)
    result = project_and_rebind_topology(vertices, quads, capture.vertices, capture.triangles,
                                         regions, guides, patch_guides, predicted, capture.plane)
    if result[3].valid:
        apply_topology_vertices(obj, result[0])
        _write_rebindings(obj.data, result[1], result[2])
    return result


def apply_topology_vertices(obj, vertices):
    if len(vertices) != len(obj.data.vertices):
        raise ValueError("Warm topology vertex count changed.")
    obj.data.vertices.foreach_set("co", np.asarray(vertices, dtype=float).ravel())
    obj.data.update()


def _topology(root, scene):
    obj = next((item for item in scene.objects if item.get("af_topology")
                and item.get("af_root_name") == root.name), None)
    if obj is None:
        raise ValueError("Current root has no topology to update.")
    return obj


def _mesh_arrays(obj):
    vertices = np.empty(len(obj.data.vertices) * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", vertices)
    quads = np.asarray([tuple(item.vertices) for item in obj.data.polygons], np.int32)
    return vertices.reshape(-1, 3), quads


def _read_bindings(mesh):
    skin = TopologySkinBinding(_values(mesh, "af_topology_skin_triangle", int),
                               _vectors(mesh, "af_topology_skin_barycentric"),
                               _values(mesh, "af_topology_skin_offset"),
                               int(_values(mesh, "af_topology_bind_schema", int)[0]))
    guide = TopologyGuideBinding(_values(mesh, "af_topology_guide_index", int),
                                 _values(mesh, "af_topology_guide_row", int),
                                 _values(mesh, "af_topology_guide_parameter"), skin.schema)
    return skin, guide


def _stored_guides(obj):
    stats = json.loads(obj.get("af_topology_stats_json", "{}"))
    return tuple(TopologyGuide(int(item["guide_index"]), item["fiber_id"],
                               item["fiber_id"], "ORIGINAL", np.asarray(item["points"]))
                 for item in stats.get("guide_layout", ()))


def _current_patch_guides(obj, guides):
    stats = json.loads(obj.get("af_topology_stats_json", "{}"))
    by_name = {item.object_name: item for item in guides}
    values = []
    for index, mapping in enumerate(stats.get("guide_map", ())):
        candidates = [by_name[name] for name in mapping["sources"] if name in by_name]
        if candidates:
            source = max(candidates, key=lambda item: _perimeter(item.points))
            values.append(TopologyGuide(index, source.fiber_id, source.object_name,
                                        source.mirror_role, source.points))
    return tuple(values)


def _perimeter(points):
    values = np.asarray(points)
    return float(np.linalg.norm(np.roll(values, -1, axis=0) - values, axis=1).sum())


def _write_rebindings(mesh, skin, guide):
    _set_values(mesh, "af_topology_skin_triangle", skin.triangle_indices)
    _set_vectors(mesh, "af_topology_skin_barycentric", skin.barycentric)
    _set_values(mesh, "af_topology_skin_offset", skin.offsets)
    _set_values(mesh, "af_topology_guide_index", guide.guide_indices)
    _set_values(mesh, "af_topology_guide_row", guide.rows)
    _set_values(mesh, "af_topology_guide_parameter", guide.parameters)


def _values(mesh, name, dtype=float):
    attribute = mesh.attributes.get(name)
    if attribute is None:
        raise ValueError(f"Topology is missing warm binding attribute {name}.")
    values = np.empty(len(mesh.vertices), dtype=dtype)
    attribute.data.foreach_get("value", values)
    return values


def _vectors(mesh, name):
    attribute = mesh.attributes.get(name)
    if attribute is None:
        raise ValueError(f"Topology is missing warm binding attribute {name}.")
    values = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    attribute.data.foreach_get("vector", values)
    return values.reshape(-1, 3)


def _face_values(mesh, name):
    attribute = mesh.attributes.get(name)
    if attribute is None:
        raise ValueError(f"Topology is missing face attribute {name}.")
    values = np.empty(len(mesh.polygons), dtype=np.int32)
    attribute.data.foreach_get("value", values)
    return values


def _set_values(mesh, name, values):
    mesh.attributes[name].data.foreach_set("value", np.asarray(values).ravel())


def _set_vectors(mesh, name, values):
    mesh.attributes[name].data.foreach_set("vector", np.asarray(values).ravel())
