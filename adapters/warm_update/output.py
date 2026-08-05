import bpy

from ..draft_skin import output as skin_output
from ..topology import output as topology_output


def replace_outputs(scene, root, skin_result=None, topology_result=None):
    prepared = _prepare(scene, root, skin_result, topology_result)
    try:
        _install(scene, root, prepared)
    except Exception:
        _rollback(prepared); raise
    _discard_old(prepared)
    selected = prepared[-1][1] if prepared else None
    if selected is not None:
        _select_only(scene, selected)
    return tuple(item[1] for item in prepared)


def _prepare(scene, root, skin_result, topology_result):
    values = []
    try:
        _prepare_skin(values, scene, root, skin_result)
        _prepare_topology(values, scene, root, topology_result)
    except Exception:
        _discard_new(values); raise
    return values


def _prepare_skin(values, scene, root, result):
    if result is None:
        return
    obj = skin_output._previous_skin(scene, root)
    values.append(("SKIN", obj, skin_output._build_mesh(result),
                   None if obj is None else obj.data, result, _snapshot(obj)))


def _prepare_topology(values, scene, root, result):
    if result is None:
        return
    obj = topology_output._previous(scene, root)
    values.append(("TOPOLOGY", obj, topology_output._build_mesh(result),
                   None if obj is None else obj.data, result, _snapshot(obj)))


def _discard_new(prepared):
    for _kind, _obj, mesh, _old, _result, _snapshot_value in prepared:
        if mesh is not None and not mesh.users:
            bpy.data.meshes.remove(mesh)


def _install(scene, root, prepared):
    for index, item in enumerate(tuple(prepared)):
        kind, obj, mesh, old, result, snapshot = item
        if obj is None:
            obj = bpy.data.objects.new(f"AF_{kind}_NEW", mesh)
            _collection(scene).objects.link(obj)
            prepared[index] = (kind, obj, mesh, old, result, snapshot)
        else:
            obj.data = mesh
        _tag(root, kind, obj, result)


def _tag(root, kind, obj, result):
    if kind == "SKIN":
        source_map = result.statistics.get("source_map", [])
        skin_output._tag_object(obj, root, result, source_map)
        obj.name = obj.data.name = "AF_DRAFT_SKIN"
    else:
        topology_output._tag(obj, root, result)
        obj.name = obj.data.name = "AF_TOPOLOGY"


def _rollback(prepared):
    for _kind, obj, mesh, old, _result, snapshot in reversed(prepared):
        if old is None:
            if obj is not None and obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        elif obj is not None:
            obj.data = old; _restore(obj, snapshot)
        if mesh is not None and not mesh.users:
            bpy.data.meshes.remove(mesh)


def _discard_old(prepared):
    for _kind, _obj, _mesh, old, _result, _snapshot_value in prepared:
        if old is not None and not old.users:
            bpy.data.meshes.remove(old)


def _snapshot(obj):
    if obj is None:
        return None
    return obj.name, obj.data.name, dict(obj.items())


def _restore(obj, snapshot):
    if snapshot is None:
        return
    obj.name, obj.data.name, values = snapshot
    for key in tuple(obj.keys()):
        del obj[key]
    for key, value in values.items():
        obj[key] = value


def _collection(scene):
    collection = bpy.data.collections.get("AF_OUTPUT")
    if collection is None:
        collection = bpy.data.collections.new("AF_OUTPUT")
    if collection.name not in {item.name for item in scene.collection.children}:
        scene.collection.children.link(collection)
    return collection


def _select_only(scene, selected):
    for obj in tuple(scene.objects):
        obj.select_set(obj == selected)
    scene.view_layers[0].objects.active = selected
