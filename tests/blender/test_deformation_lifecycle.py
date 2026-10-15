"""Blender ID remapping, append/export, undo/redo and compatibility guards."""
import sys
import tempfile
from pathlib import Path
import bpy
import numpy as np
ROOT = Path(__file__).resolve().parents[2]; sys.path[:0] = [str(ROOT.parent),str(ROOT),str(Path(__file__).parent)]
from test_deformation_storage import fixture, objects
from anthroforge.adapters.deformation.storage import load
from anthroforge.adapters.deformation.publication import compatible


def duplicate(root, obj, reference):
    bpy.ops.object.select_all(action="DESELECT"); root.select_set(True); obj.select_set(True)
    bpy.context.view_layer.objects.active = obj; bpy.ops.object.duplicate()
    copies = list(bpy.context.selected_objects); copied_root = next(o for o in copies if o.type == "EMPTY")
    copied_mesh = next(o for o in copies if o.type == "MESH")
    assert copied_root["af_deformation_mesh"] == copied_mesh
    assert copied_mesh["af_deformation_root"] == copied_root
    assert copied_mesh.data != obj.data and load(copied_root,copied_mesh).signature == reference.signature
    return copied_root,copied_mesh


def append(path, root_name, signature):
    with bpy.data.libraries.load(str(path),link=False) as (source,target): target.objects = [root_name]
    root = target.objects[0]; obj = root["af_deformation_mesh"]
    bpy.context.scene.collection.objects.link(root); bpy.context.scene.collection.objects.link(obj)
    assert obj["af_deformation_root"] == root and load(root,obj).signature == signature


def undo(root, obj, signature):
    bpy.context.preferences.edit.use_global_undo = True; names = root.name,obj.name
    bpy.ops.ed.undo_push(message="Reference baseline"); obj.data.vertices[0].co.x += 2
    bpy.ops.ed.undo_push(message="Position edit"); bpy.ops.ed.undo()
    root,obj = (bpy.data.objects[name] for name in names)
    assert load(root,obj).signature == signature
    assert abs(obj.data.vertices[0].co.x)<1e-7
    bpy.ops.ed.redo(); obj = bpy.data.objects[names[1]]
    assert abs(obj.data.vertices[0].co.x-2)<1e-7


def guards(obj):
    modifier = obj.modifiers.new("Guard rig","ARMATURE")
    try:
        try: compatible(obj)
        except ValueError as error: assert "rig" in str(error)
        else: raise AssertionError("Rigged mesh was accepted")
    finally: obj.modifiers.remove(modifier)


def run():
    reference = fixture(); root,obj = objects(reference); root_name = root.name
    duplicate(root,obj,reference); guards(obj)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)/"export.blend"; bpy.data.libraries.write(str(path),{root,obj},fake_user=True)
        append(path,root_name,reference.signature)
    undo(root,obj,reference.signature)
    print("DEFORMATION_LIFECYCLE_PASS",flush=True)


if __name__ == "__main__": run()
