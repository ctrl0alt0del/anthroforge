import json

import bpy

try:
    from ...core.topology.constants import SOLVER_VERSION
except ImportError:
    from core.topology.constants import SOLVER_VERSION


def replace_topology(scene, root, result):
    previous = _previous(scene, root)
    mesh = _build_mesh(result)
    if previous is not None:
        return _replace(scene, root, result, previous, mesh)
    return _create(scene, root, result, mesh)


def _build_mesh(result):
    mesh = bpy.data.meshes.new("AF_TOPOLOGY_NEW")
    mesh.from_pydata(result.vertices.tolist(), [], result.quads.tolist())
    mesh.update(calc_edges=True)
    _write_attribute(mesh, "af_topology_region", result.face_regions)
    _write_attribute(mesh, "af_topology_guide_index", result.guide_indices)
    _write_point_attribute(mesh, "af_topology_owner_scp_index", result.owner_scp_indices, "INT")
    _write_point_attribute(mesh, "af_topology_target_edge_length", result.target_edge_lengths, "FLOAT")
    return mesh


def _write_attribute(mesh, name, values):
    attribute = mesh.attributes.new(name, "INT", "FACE")
    attribute.data.foreach_set("value", values.astype(int).ravel())


def _write_point_attribute(mesh, name, values, data_type):
    if values is None or len(values) != len(mesh.vertices):
        return
    attribute = mesh.attributes.new(name, data_type, "POINT")
    attribute.data.foreach_set("value", values.ravel())


def _create(scene, root, result, mesh):
    obj = bpy.data.objects.new("AF_TOPOLOGY_NEW", mesh)
    try:
        _output_collection(scene).objects.link(obj)
        _finish(scene, root, result, obj)
    except Exception:
        _remove(obj); raise
    return obj


def _replace(scene, root, result, obj, mesh):
    previous = obj.data
    obj.data = mesh
    try:
        _finish(scene, root, result, obj)
    except Exception:
        obj.data = previous; bpy.data.meshes.remove(mesh); raise
    if previous is not None and not previous.users:
        bpy.data.meshes.remove(previous)
    return obj


def _finish(scene, root, result, obj):
    _tag(obj, root, result)
    obj.name = obj.data.name = "AF_TOPOLOGY"
    _select_only(scene, obj)


def _tag(obj, root, result):
    obj["af_topology"] = True
    obj["af_root_name"] = root.name
    obj["af_topology_input_hash"] = str(result.statistics.get("input_hash", ""))
    obj["af_topology_solver_version"] = SOLVER_VERSION
    obj["af_topology_stats_json"] = json.dumps(result.statistics, sort_keys=True)
    obj["af_topology_guide_map_json"] = json.dumps(result.statistics.get("guide_map", []), sort_keys=True)
    obj["af_topology_owner_map_json"] = json.dumps(result.statistics.get("owner_map", {}), sort_keys=True)


def _previous(scene, root):
    return next((obj for obj in scene.objects if obj.get("af_topology")
                 and obj.get("af_root_name") == root.name), None)


def _output_collection(scene):
    collection = bpy.data.collections.get("AF_OUTPUT")
    if collection is None:
        collection = bpy.data.collections.new("AF_OUTPUT")
    if collection.name not in {item.name for item in scene.collection.children}:
        scene.collection.children.link(collection)
    return collection


def _remove(obj):
    mesh = None if obj is None else obj.data
    if obj is not None:
        bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and not mesh.users:
        bpy.data.meshes.remove(mesh)


def _select_only(scene, selected):
    for obj in tuple(scene.objects):
        obj.select_set(obj == selected)
    scene.view_layers[0].objects.active = selected
