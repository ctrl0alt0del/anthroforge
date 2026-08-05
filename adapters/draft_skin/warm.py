import json

import numpy as np

from .capture import capture_skin

try:
    from ...core.warm_start.model import SkinWarmBinding, SkinWarmCapture
    from ...core.warm_start.signatures import geometry_state_hash, solver_settings_hash, structural_signature
except ImportError:
    from core.warm_start.model import SkinWarmBinding, SkinWarmCapture
    from core.warm_start.signatures import geometry_state_hash, solver_settings_hash, structural_signature


def capture_warm_skin(root, scene, depsgraph, current=None):
    obj = _draft_skin(root, scene)
    vertices, triangles = _mesh_arrays(obj)
    binding = _read_binding(obj.data)
    current = current or capture_skin(root, scene, depsgraph)
    stats = json.loads(obj.get("af_skin_stats_json", "{}"))
    return SkinWarmCapture(vertices, triangles, binding, (), current.sources,
                           structural_signature(len(vertices), triangles),
                           stats.get("source_connectivity_signature", ""),
                           geometry_state_hash(current.sources), solver_settings_hash(current.settings),
                           stats.get("source_identity_signature", ""),
                           stats.get("source_connectivity_signature", ""),
                           stats.get("source_identity_signature", ""),
                           stats.get("structural_signature", ""),
                           stats.get("solver_settings_hash", ""))


def apply_warm_skin(obj, result):
    if not result.status.valid or len(result.vertices) != len(obj.data.vertices):
        raise ValueError("Cannot apply an invalid warm skin result.")
    obj.data.vertices.foreach_set("co", np.asarray(result.vertices, dtype=float).ravel())
    obj.data.update()


def _draft_skin(root, scene):
    obj = next((item for item in scene.objects if item.get("af_draft_skin")
                and item.get("af_root_name") == root.name), None)
    if obj is None:
        raise ValueError("Current root has no draft skin to update.")
    return obj


def _mesh_arrays(obj):
    obj.data.calc_loop_triangles()
    vertices = np.empty(len(obj.data.vertices) * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", vertices)
    triangles = np.asarray([tuple(item.vertices) for item in obj.data.loop_triangles], np.int32)
    return vertices.reshape(-1, 3), triangles


def _read_binding(mesh):
    sources = np.column_stack([_values(mesh, f"af_skin_bind_source_{i}", int) for i in range(4)])
    triangles = np.column_stack([_values(mesh, f"af_skin_bind_triangle_{i}", int) for i in range(4)])
    barycentric = np.stack([_vectors(mesh, f"af_skin_bind_barycentric_{i}") for i in range(4)], axis=1)
    weights = np.column_stack([_values(mesh, f"af_skin_bind_weight_{i}") for i in range(4)])
    schema = int(_values(mesh, "af_skin_bind_schema", int)[0])
    return SkinWarmBinding(sources, triangles, barycentric, weights,
                           _values(mesh, "af_skin_bind_normal_offset"),
                           _values(mesh, "af_skin_bind_support"), schema)


def _values(mesh, name, dtype=float):
    attribute = mesh.attributes.get(name)
    if attribute is None:
        raise ValueError(f"Draft skin is missing warm binding attribute {name}.")
    values = np.empty(len(mesh.vertices), dtype=dtype)
    attribute.data.foreach_get("value", values)
    return values


def _vectors(mesh, name):
    attribute = mesh.attributes.get(name)
    if attribute is None:
        raise ValueError(f"Draft skin is missing warm binding attribute {name}.")
    values = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    attribute.data.foreach_get("vector", values)
    return values.reshape(-1, 3)
