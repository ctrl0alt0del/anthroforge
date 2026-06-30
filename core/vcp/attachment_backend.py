from ..attachment_codec import encode_fiber_surface_param, fiber_surface_param, is_fiber_legacy_attach
from ..scp_proxy.signature import mesh_topology_signature, open_evaluated_mesh
from ..scp_runtime.common import as_id, find_geometry_mesh_scp_obj
from ..scp_runtime.surface import frame_from_parent_param, nearest_parent_param_from_world
from ..utils import depsgraph_for_scene, scene_for_id


def attachment_runtime(scene=None, depsgraph=None):
    return {"depsgraph": depsgraph or depsgraph_for_scene(scene), "surface_cache": {}}


def _runtime_depsgraph(scene, runtime):
    data = runtime or {}
    return data.get("depsgraph") or depsgraph_for_scene(scene)


def _runtime_cache(runtime):
    data = runtime if isinstance(runtime, dict) else None
    return {} if data is None else data.setdefault("surface_cache", {})


def _parent_mesh(root, scene, parent_id):
    return None if root is None else find_geometry_mesh_scp_obj(scene, root.name, parent_id)


def _capture_param(parent_obj, world_point, scene, runtime):
    depsgraph = _runtime_depsgraph(scene, runtime)
    cache = _runtime_cache(runtime)
    return None if depsgraph is None else nearest_parent_param_from_world(parent_obj, world_point, depsgraph, cache=cache)


def _capture_raw(parent_obj, world_point, scene, runtime):
    param = None if parent_obj is None else _capture_param(parent_obj, world_point, scene, runtime)
    return None if param is None else encode_fiber_surface_param(param)


def capture_attachment_from_world(root, scene, parent_id, world_point, runtime=None):
    return _capture_raw(_parent_mesh(root, scene, parent_id), world_point, scene, runtime)


def _mesh_vertex_world(parent_obj, vertex_index):
    verts = getattr(getattr(parent_obj, "data", None), "vertices", ())
    return None if not (0 <= int(vertex_index) < len(verts)) else parent_obj.matrix_world @ verts[int(vertex_index)].co.copy()


def capture_attachment_from_mesh_vertex(root, scene, parent_id, vertex_index, runtime=None):
    parent_obj = _parent_mesh(root, scene, parent_id)
    world = None if parent_obj is None else _mesh_vertex_world(parent_obj, vertex_index)
    return None if world is None else _capture_raw(parent_obj, world, scene, runtime)


def _eval_vertex_world(parent_obj, scene, vertex_index, signature, runtime):
    eval_obj, mesh = open_evaluated_mesh(scene, parent_obj, depsgraph=_runtime_depsgraph(scene, runtime), refresh=False)
    try:
        valid = mesh is not None and (not signature or mesh_topology_signature(mesh) == str(signature or ""))
        return None if not valid or not (0 <= int(vertex_index) < len(mesh.vertices)) else eval_obj.matrix_world @ mesh.vertices[int(vertex_index)].co.copy()
    finally:
        None if eval_obj is None else eval_obj.to_mesh_clear()


def capture_attachment_from_proxy_vertex(root, scene, parent_id, vertex_index, signature="", runtime=None):
    parent_obj = _parent_mesh(root, scene, parent_id)
    world = None if parent_obj is None else _eval_vertex_world(parent_obj, scene, vertex_index, signature, runtime)
    return None if world is None else _capture_raw(parent_obj, world, scene, runtime)


def _resolved_frame(root, scene, parent_id, raw, runtime):
    parent_obj = _parent_mesh(root, scene, parent_id)
    param = fiber_surface_param(raw)
    depsgraph = _runtime_depsgraph(scene, runtime)
    cache = _runtime_cache(runtime)
    ok = parent_obj is not None and param is not None and depsgraph is not None
    return None if not ok else frame_from_parent_param(parent_obj, param, depsgraph, cache=cache)


def resolve_attachment_world(root, scene, parent_id, raw, runtime=None):
    frame = _resolved_frame(root, scene, parent_id, raw, runtime)
    return None if frame is None else frame["point_world"].copy()


def resolve_attachment_normal(root, scene, parent_id, raw, runtime=None):
    frame = _resolved_frame(root, scene, parent_id, raw, runtime)
    return None if frame is None else frame["normal_world"].copy()


def attachment_issue(root, scene, parent_id, raw, runtime=None):
    if not as_id(parent_id):
        return "Missing parent SCP."
    if is_fiber_legacy_attach(raw):
        return "Legacy attachment; recreate this fiber anchor."
    if fiber_surface_param(raw) is None:
        return "Invalid attachment payload."
    if _parent_mesh(root, scene, parent_id) is None:
        return "Missing parent geometry."
    return "" if _resolved_frame(root, scene, parent_id, raw, runtime) is not None else "Attachment no longer resolves."


def capture_attachment_from_object(parent_obj, world_point, runtime=None):
    if parent_obj is None:
        return None
    return _capture_raw(parent_obj, world_point, scene_for_id(parent_obj), runtime)
