import hashlib

from ..utils import depsgraph_for_scene, update_scene_view_layer


def _update_ints(digest, values):
    digest.update(",".join(str(int(value)) for value in tuple(values or ())).encode("ascii"))
    digest.update(b";")


def open_evaluated_mesh(scene, obj, depsgraph=None, refresh=True):
    depsgraph = depsgraph or depsgraph_for_scene(scene)
    if depsgraph is None or obj is None or getattr(obj, "type", "") != "MESH":
        return None, None
    update_scene_view_layer(scene) if refresh else None
    eval_obj = obj.evaluated_get(depsgraph)
    return eval_obj, eval_obj.to_mesh()


def close_evaluated_mesh(eval_obj):
    None if eval_obj is None else eval_obj.to_mesh_clear()


def mesh_topology_signature(mesh):
    digest = hashlib.sha1()
    _update_ints(digest, (len(mesh.vertices), len(mesh.edges), len(mesh.polygons)))
    for edge in mesh.edges:
        _update_ints(digest, edge.vertices)
    for poly in mesh.polygons:
        _update_ints(digest, poly.vertices)
    return digest.hexdigest()


def topology_signature(scene, obj, depsgraph=None, refresh=True):
    eval_obj, mesh = open_evaluated_mesh(scene, obj, depsgraph=depsgraph, refresh=refresh)
    if mesh is None:
        raise RuntimeError("Could not evaluate mesh.")
    try:
        return mesh_topology_signature(mesh)
    finally:
        close_evaluated_mesh(eval_obj)


def snapshot_row(scene, item, depsgraph=None, refresh=True):
    data = getattr(item.obj, "data", None)
    return {"scp_id": item.scp_id, "object_name": item.obj.name, "mesh_name": "" if data is None else data.name, "signature": topology_signature(scene, item.obj, depsgraph=depsgraph, refresh=refresh)}


def snapshot_key(item):
    data = getattr(item.obj, "data", None)
    return item.scp_id, item.obj.name, "" if data is None else data.name
