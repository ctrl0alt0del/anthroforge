import json

import bpy
import numpy as np

try:
    from ...core.draft_skin.constants import SOLVER_VERSION
except ImportError:
    from core.draft_skin.constants import SOLVER_VERSION


def replace_draft_skin(scene, root, result, source_map):
    previous = _previous_skin(scene, root)
    mesh = _build_mesh(result)
    if previous is not None:
        return _replace_mesh(scene, root, result, source_map, previous, mesh)
    return _create_object(scene, root, result, source_map, mesh)


def _create_object(scene, root, result, source_map, mesh):
    obj = bpy.data.objects.new("AF_DRAFT_SKIN_NEW", mesh)
    try:
        _output_collection(scene).objects.link(obj)
        _finish_object(scene, root, result, source_map, obj)
    except Exception:
        _remove_object(obj)
        raise
    return obj


def _replace_mesh(scene, root, result, source_map, obj, mesh):
    previous = obj.data
    obj.data = mesh
    try:
        _finish_object(scene, root, result, source_map, obj)
    except Exception:
        obj.data = previous
        bpy.data.meshes.remove(mesh)
        raise
    if previous is not None and not previous.users:
        bpy.data.meshes.remove(previous)
    return obj


def _finish_object(scene, root, result, source_map, obj):
    _tag_object(obj, root, result, source_map)
    obj.name = obj.data.name = "AF_DRAFT_SKIN"
    _select_only(scene, obj)


def _build_mesh(result):
    mesh = bpy.data.meshes.new("AF_DRAFT_SKIN_NEW")
    mesh.from_pydata(result.vertices.tolist(), [], result.triangles.tolist())
    mesh.update(calc_edges=True)
    _write_collagen(mesh, result.collagen)
    _write_bindings(mesh, result.binding)
    return mesh


def _write_collagen(mesh, values):
    attribute = mesh.attributes.new("af_skin_collagen", "FLOAT", "POINT")
    attribute.data.foreach_set("value", values.astype(float).ravel())


def _write_bindings(mesh, binding):
    if binding is None:
        return
    for index in range(4):
        _point_value(mesh, f"af_skin_bind_source_{index}", "INT", binding.source_indices[:, index])
        _point_value(mesh, f"af_skin_bind_triangle_{index}", "INT", binding.triangle_indices[:, index])
        _point_vector(mesh, f"af_skin_bind_barycentric_{index}", binding.barycentric[:, index])
        _point_value(mesh, f"af_skin_bind_weight_{index}", "FLOAT", binding.weights[:, index])
    _point_value(mesh, "af_skin_bind_normal_offset", "FLOAT", binding.normal_offsets)
    _point_value(mesh, "af_skin_bind_support", "FLOAT", binding.support)
    _point_value(mesh, "af_skin_bind_schema", "INT", [binding.schema] * len(mesh.vertices))


def _point_value(mesh, name, data_type, values):
    attribute = mesh.attributes.new(name, data_type, "POINT")
    field = "value"
    attribute.data.foreach_set(field, np.asarray(values).ravel())


def _point_vector(mesh, name, values):
    attribute = mesh.attributes.new(name, "FLOAT_VECTOR", "POINT")
    attribute.data.foreach_set("vector", np.asarray(values, dtype=float).ravel())


def _output_collection(scene):
    collection = bpy.data.collections.get("AF_OUTPUT")
    if collection is None:
        collection = bpy.data.collections.new("AF_OUTPUT")
    if collection.name not in {item.name for item in scene.collection.children}:
        scene.collection.children.link(collection)
    return collection


def _tag_object(obj, root, result, source_map):
    obj["af_draft_skin"] = True
    obj["af_root_name"] = root.name
    obj["af_skin_input_hash"] = str(result.statistics.get("input_hash", ""))
    obj["af_skin_solver_version"] = SOLVER_VERSION
    obj["af_skin_stats_json"] = json.dumps(result.statistics, sort_keys=True)
    obj["af_skin_source_map_json"] = json.dumps(source_map, sort_keys=True)


def _previous_skin(scene, root):
    return next(
        (obj for obj in scene.objects if obj.get("af_draft_skin") and obj.get("af_root_name") == root.name),
        None,
    )


def _remove_object(obj):
    if obj is None:
        return
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and not mesh.users:
        bpy.data.meshes.remove(mesh)


def _select_only(scene, selected):
    for obj in tuple(scene.objects):
        obj.select_set(obj == selected)
    scene.view_layers[0].objects.active = selected
