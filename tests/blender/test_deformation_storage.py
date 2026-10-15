"""Run in background Blender: durable data and position-only publication."""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import bpy
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT.parent), str(ROOT)]
from anthroforge.adapters.deformation.storage import store, load
from anthroforge.adapters.deformation.publication import install_ids, publish, compatible
from anthroforge.core.deformation.reference import DeformationReference, SCHEMA, CAPABILITY


def fixture():
    points = np.array([[0.,0.,0.],[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]])
    arrays = dict(vertices=points, quads=np.array([[0,1,2,3]]), vertex_ids=np.arange(4),
        proxy_vertices=points, proxy_tets=np.array([[0,1,2,3]]), samples=points,
        sample_weights=np.full(4,.25), sample_owners=np.zeros(4,np.int32), sample_addresses=np.arange(4))
    return DeformationReference(arrays,dict(schema=SCHEMA,capability=CAPABILITY,
        contributors=[dict(key="bone",vertex_count=4)]))


def objects(reference):
    root = bpy.data.objects.new("REF_TEST_ROOT",None); bpy.context.scene.collection.objects.link(root)
    mesh = bpy.data.meshes.new("REF_TEST_MESH")
    mesh.from_pydata(reference.arrays["vertices"],[],reference.arrays["quads"])
    obj = bpy.data.objects.new("REF_TEST_SKIN",mesh); bpy.context.scene.collection.objects.link(obj)
    mesh.uv_layers.new(name="PreservedUV")
    mesh.attributes.new("PreservedAttribute","FLOAT","POINT").data[0].value = .75
    install_ids(obj,reference); store(root,obj,reference)
    return root,obj


def verify_publication(root,obj,reference):
    mesh = obj.data; pointer = mesh.as_pointer(); positions = reference.arrays["vertices"]+.1
    result = SimpleNamespace(vertices=positions,quads=reference.arrays["quads"],statistics={"test":True},validation=None)
    publish(root,obj,result,reference.signature)
    assert obj.data.as_pointer() == pointer and "PreservedUV" in mesh.uv_layers
    assert mesh.attributes["PreservedAttribute"].data[0].value == .75
    actual = np.array([v.co[:] for v in mesh.vertices]); np.testing.assert_allclose(actual,positions,atol=1e-7)
    obj.shape_key_add(name="Basis")
    try:
        compatible(obj)
    except ValueError as error:
        assert "shape keys" in str(error)
    else:
        raise AssertionError("Shape-key mesh was not protected")


def main():
    reference = fixture(); root,obj = objects(reference)
    with tempfile.TemporaryDirectory() as folder:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(folder)/"reference.blend"))
        bpy.ops.wm.open_mainfile(filepath=str(Path(folder)/"reference.blend"))
        root,obj = bpy.data.objects["REF_TEST_ROOT"],bpy.data.objects["REF_TEST_SKIN"]
        restored = load(root,obj); assert restored.signature == reference.signature
        assert not any(o.get("af_draft_skin") for o in bpy.data.objects)
        verify_publication(root,obj,restored)
    print("DEFORMATION_STORAGE_PASS",flush=True)


if __name__ == "__main__": main()
