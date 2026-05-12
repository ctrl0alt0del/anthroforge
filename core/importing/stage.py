from dataclasses import dataclass, field

import bpy

_DATA_LISTS = {
    "Armature": "armatures",
    "Curve": "curves",
    "Lattice": "lattices",
    "Light": "lights",
    "Mesh": "meshes",
    "MetaBall": "metaballs",
}


@dataclass
class StageBundle:
    root: object = None
    objects: list[object] = field(default_factory=list)


def _object_ptrs():
    return {obj.as_pointer() for obj in bpy.data.objects}


def _new_objects(before):
    return [obj for obj in bpy.data.objects if obj.as_pointer() not in before]


def _alive(obj):
    try:
        obj.as_pointer()
    except ReferenceError:
        return False
    return obj is not None


def append_stage_root(filepath, root_name):
    before = _object_ptrs()
    with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
        if root_name not in data_from.objects:
            return StageBundle()
        data_to.objects = [root_name]
    return StageBundle(root=data_to.objects[0], objects=_new_objects(before))


def stage_bound_map(stage_root):
    out = {}
    for scp in stage_root.af_scp_system.scps:
        for entry in scp.bound_objects:
            obj = getattr(entry, "object_ref", None)
            if obj is not None:
                out[(str(scp.id or ""), str(entry.id or ""))] = obj
    return out


def remove_stage_root(stage):
    if _alive(stage.root) and stage.root.name in bpy.data.objects:
        bpy.data.objects.remove(stage.root, do_unlink=True)


def _data_store(data):
    name = _DATA_LISTS.get(getattr(getattr(data, "bl_rna", None), "identifier", ""), "")
    return None if not name else getattr(bpy.data, name, None)


def _remove_data(data):
    store = _data_store(data)
    if data is not None and store is not None and data.users == 0:
        store.remove(data)


def _remove_object(obj):
    if not _alive(obj) or obj.name not in bpy.data.objects:
        return
    data = getattr(obj, "data", None)
    bpy.data.objects.remove(obj, do_unlink=True)
    _remove_data(data)


def remove_unused_stage_objects(stage, keep):
    keep_ids = {obj.as_pointer() for obj in keep if _alive(obj)}
    for obj in stage.objects:
        if _alive(obj) and obj.as_pointer() not in keep_ids:
            _remove_object(obj)
