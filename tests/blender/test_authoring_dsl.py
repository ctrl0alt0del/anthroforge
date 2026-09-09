"""End-to-end authoring uses real SCPs, native V3 and editable entities."""
import json
import tempfile
from pathlib import Path
import bpy
import numpy as np
from unittest.mock import patch
from _helpers import BlenderTestCase, root, scp_with_object
from anthroforge.adapters.authoring.native_scene import BlenderScene
from anthroforge.app.authoring.api import execute
from anthroforge.core.authoring.schema import validate
from anthroforge.core.authoring.storage import FileStore


def fixture(root_obj):
    path = Path(__file__).parents[1] / "fixtures/authoring/02-upper-arm.json"
    document = json.loads(path.read_text())
    document["context"]["reference_pose"] = "rest"
    document["policies"]["default"]["solver_budget_ms"] = 30000
    for index, name in enumerate(("origin", "guide", "insertion")):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 2-index*2))
        scp = scp_with_object(root_obj, name, bpy.context.object)
        document["targets"][name]["binding"]["id"] = scp.id
    for name, z in (("origin", 0), ("insertion", 1)):
        for seed in document["regions"][name]["definition"]["seeds"]:
            seed[2] = z
    return document


def message(root_obj, operation, **params):
    return dict(dsl="anthroforge.authoring.protocol", version="0.2.0", message_type="request",
                request_id=operation + "_test", op=operation, params=dict(scene_id=root_obj.name, **params))


def build(root_obj, directory):
    document = fixture(root_obj)
    revision = BlenderScene(root_obj, bpy.context.scene).capture(root_obj.name).revision
    request = message(root_obj, "build", expected_scene_revision=revision, document=document, transaction="document_atomic")
    result = execute(request, root_obj, bpy.context.scene, directory)
    print("AUTHORING_RESULT", json.dumps(result), flush=True)
    return result, request


class AuthoringBlenderTests(BlenderTestCase):
    def test_closed_loft_publishes_native_loop_anchors(self):
        from _authoring_loop_fixture import fixture as loop_fixture
        r = root()
        document = loop_fixture(r)
        revision = BlenderScene(r,bpy.context.scene).capture(r.name).revision
        request = message(r,"build",document=document,expected_scene_revision=revision,transaction="document_atomic")
        with tempfile.TemporaryDirectory() as directory:
            result = execute(request,r,bpy.context.scene,directory)
        self.assertTrue(result["published"],result)
        self.assertEqual(len(r.af_vcp_system.fibers),2)
        self.assertTrue(all(len(f.loop_anchors) == 4 and f.topology_mode == "LOOP" for f in r.af_vcp_system.fibers))

    def test_build_edit_and_replay(self):
        r = root()
        with tempfile.TemporaryDirectory() as directory:
            result, request = build(r, directory)
            self.assertTrue(result["published"], result["diagnostics"])
            validate(result, "protocol")
            self.assertEqual(len(r.af_vcp_system.muscles), 1)
            self.assertEqual(len(r.af_vcp_system.fibers), 5)
            self.assertTrue(all(f.node_attachments_json for f in r.af_vcp_system.fibers))
            verify_selection(self, r)
            self.assertEqual(execute(request, r, bpy.context.scene, directory), result)
            verify_patch(self, r, directory)
            verify_volume(self, r)

    def test_persists_in_blend_without_external_journal(self):
        r = root()
        with tempfile.TemporaryDirectory() as directory:
            result, request = build(r, directory)
            self.assertTrue(result["published"], result)
            before = np.array([tuple(v.co) for v in inflated(r).data.vertices])
            path = str(Path(directory)/"roundtrip.blend")
            bpy.ops.wm.save_as_mainfile(filepath=path)
            bpy.ops.wm.open_mainfile(filepath=path)
            r = bpy.data.objects["AF_ROOT"]
            BlenderScene(r,bpy.context.scene).refresh()
            after = np.array([tuple(v.co) for v in inflated(r).data.vertices])
            np.testing.assert_allclose(before,after,atol=1e-6)
            replay = execute(request,r,bpy.context.scene,Path(directory)/"empty_journal")
            self.assertTrue(replay["published"],replay)

    def test_rolls_back_on_document_write_failure(self):
        r = root()
        with tempfile.TemporaryDirectory() as directory:
            result, _ = build(r,directory)
            self.assertTrue(result["published"],result)
            original = BlenderScene(r,bpy.context.scene).capture(r.name).revision
            before = np.array([tuple(v.co) for v in inflated(r).data.vertices])
            request = patch_request(r, "/recipes/pattern/construction/stations/1/offset/value", .03)
            original_put = FileStore.put
            with patch.object(FileStore,"put",failing_document_write(original_put)):
                result = execute(request,r,bpy.context.scene,directory)
            self.assertEqual(result["status"],"failed",result)
            self.assertEqual(BlenderScene(r,bpy.context.scene).capture(r.name).revision,original)
            np.testing.assert_allclose(before,[tuple(v.co) for v in inflated(r).data.vertices],atol=1e-7)


def patch_request(root_obj, path, value):
    revision = BlenderScene(root_obj,bpy.context.scene).capture(root_obj.name).revision
    return message(root_obj,"patch",document_id="upper_arm_pattern",expected_document_revision=1,
                   expected_scene_revision=revision,operations=[dict(op="replace",path=path,value=value)],
                   rebuild="affected")


def failing_document_write(original):
    def write(store, category, key, value):
        if category == "documents":
            raise OSError("Injected disk failure")
        return original(store,category,key,value)
    return write


def verify_patch(test,root_obj,directory):
    ids = [f.id for f in root_obj.af_vcp_system.fibers]
    request = patch_request(root_obj,"/volume_presets/baseline/amount/fraction",.06)
    result = execute(request,root_obj,bpy.context.scene,directory)
    test.assertTrue(result["published"],result)
    test.assertEqual(result["cost"]["fibers_solved"]["value"],0)
    test.assertEqual(ids,[f.id for f in root_obj.af_vcp_system.fibers])


def inflated(root_obj):
    return next(o for o in bpy.context.scene.objects if o.get("af_muscle_surface") == "INFL"
                and o.get("af_root_name") == root_obj.name)


def verify_volume(test, root_obj):
    muscle = root_obj.af_vcp_system.muscles[0]
    before = np.array([tuple(v.co) for v in inflated(root_obj).data.vertices])
    muscle.inflation_max_value *= 1.5
    BlenderScene(root_obj, bpy.context.scene).refresh()
    after = np.array([tuple(v.co) for v in inflated(root_obj).data.vertices])
    test.assertGreater(float(np.max(np.linalg.norm(after-before, axis=1))), .01)


def verify_selection(test, root_obj):
    identity = root_obj.af_vcp_system.muscles[0].id
    result = bpy.ops.af.select_vcp_in_tree(node_type="MUSCLE",node_id=identity)
    test.assertEqual(result,{"FINISHED"})
    test.assertEqual(bpy.context.active_object.get("af_muscle_id"),identity)
    test.assertFalse(bpy.context.active_object.hide_select)
