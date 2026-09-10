"""0.3 draft correction, native boundary persistence and publication checks."""
import tempfile
from pathlib import Path
import bpy
import numpy as np
from unittest.mock import patch
from _helpers import BlenderTestCase, root
from test_authoring_dsl import fixture, message, inflated
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.native_scene import BlenderScene
from anthroforge.core.authoring.schema import validate


def document(root_obj):
    value = fixture(root_obj)
    value["version"] = "0.3.0"
    build = value["recipes"]["pattern"]["construction"]
    build["boundary_conformance"] = dict(stations=[build["stations"][i]["id"] for i in (0,-1)],
        max_error=dict(value=.0001,unit="scene"),blend_span=.1,max_samples=129)
    return value


def request(root_obj,operation,**params):
    value = message(root_obj,operation,**params)
    value["version"] = "0.3.0"
    value["params"]["expected_scene_revision"] = BlenderScene(root_obj,bpy.context.scene).capture(root_obj.name).revision
    return value


class AuthoringV03BlenderTests(BlenderTestCase):
    def test_mapping_failure_preserves_draft_revision(self):
        r = root()
        value = document(r)
        value["targets"]["origin"]["binding"]["id"] = "SCP_MISSING"
        with tempfile.TemporaryDirectory() as directory:
            result = execute(request(r,"draft",document=value,expected_draft_revision=0),r,bpy.context.scene,directory)
            validate(result,"protocol")
            self.assertEqual(result["draft_revision"],1,result)
            self.assertEqual(result["diagnostics"][0]["code"],"TARGET_NOT_FOUND")
            payload = message(r,"export",document_id=value["document_id"],include="authoring",source="draft")
            payload["version"] = "0.3.0"
            exported = execute(payload,r,bpy.context.scene,directory)
            self.assertEqual(exported["status"],"success",exported)

    def test_mirror_scheduler_respects_explicit_fibers(self):
        from anthroforge.core.visualization import vcp_mirror_runtime as runtime
        r = root()
        fiber = r.af_vcp_system.fibers.add()
        fiber.a_parent_id = "SCP_A"
        fiber["af_authoring_symmetry"] = "explicit"
        rule = ("X",(0,0,0))
        with patch.object(runtime,"_rule_for_scp",return_value=rule) as lookup:
            self.assertIsNone(runtime._rule_for_fiber(fiber,{},{}))
            lookup.assert_not_called()
            del fiber["af_authoring_symmetry"]
            self.assertEqual(runtime._rule_for_fiber(fiber,{},{}),rule)

    def test_capabilities_match_protocol_version(self):
        r = root()
        with tempfile.TemporaryDirectory() as directory:
            for version in ("0.2.0","0.3.0"):
                payload = message(r,"describe",scope="capabilities")
                payload.update(version=version,request_id="describe_"+version)
                result = execute(payload,r,bpy.context.scene,directory)
                validate(result,"protocol")
                self.assertEqual("draft" in result["capabilities"]["operations"],version == "0.3.0")

    def test_failed_draft_can_be_corrected_and_published(self):
        r = root()
        value = document(r)
        check = dict(metric="section_width",s=.5,u_range=[0,1],statistic="max",minimum=dict(value=100,unit="scene"),maximum=dict(value=101,unit="scene"))
        value["volume_presets"]["baseline"]["shape_checks"] = [check]
        with tempfile.TemporaryDirectory() as directory:
            result = execute(request(r,"draft",document=value,expected_draft_revision=0),r,bpy.context.scene,directory)
            validate(result,"protocol")
            self.assertEqual(result["status"],"unresolved",result)
            self.assertEqual(result["draft_revision"],1)
            self.assertEqual(len(r.af_vcp_system.muscles),0)
            repair_and_publish(self,r,directory,value["document_id"])

    def test_boundaries_survive_without_authoring_documents(self):
        r = root()
        with tempfile.TemporaryDirectory() as directory:
            result = execute(request(r,"build",document=document(r),transaction="document_atomic"),r,bpy.context.scene,directory)
            self.assertTrue(result["published"],result)
            before = np.array([tuple(v.co) for v in inflated(r).data.vertices])
            verify_detached_reload(self,r,directory,before)

    def test_boundaries_follow_scp_geometry_without_regions(self):
        r = root()
        with tempfile.TemporaryDirectory() as directory:
            result = execute(request(r,'build',document=document(r),transaction='document_atomic'),r,bpy.context.scene,directory)
            self.assertTrue(result['published'],result)
            verify_geometric_motion(self,r)


def verify_detached_reload(test,r,directory,before):
    from anthroforge.core.authoring.regions import RegionResolver
    test.assertNotIn('af_authoring_material', r.af_vcp_system.fiber_surfaces[0])
    test.assertNotIn('af_authoring_material', r.af_vcp_system.muscles[0])
    r.pop('af_authoring_documents',None); r.pop('af_authoring_journal',None)
    path = str(Path(directory)/'boundary.blend')
    with patch.object(RegionResolver,'__init__',side_effect=AssertionError('Runtime read regions')):
        bpy.ops.wm.save_as_mainfile(filepath=path)
        bpy.ops.wm.open_mainfile(filepath=path)
        r = bpy.data.objects['AF_ROOT']
        BlenderScene(r,bpy.context.scene).refresh()
        np.testing.assert_allclose(before,[tuple(v.co) for v in inflated(r).data.vertices],atol=1e-6)
        from test_authoring_dsl import verify_volume
        verify_volume(test,r)


def verify_geometric_motion(test,r):
    from anthroforge.core.authoring.regions import RegionResolver
    from anthroforge.core.visualization.fiber_node_attachment_runtime import apply_fiber_node_attachments
    from anthroforge.core.scp_runtime.common import find_geometry_mesh_scp_obj
    fiber = r.af_vcp_system.fibers[0]
    with patch.object(RegionResolver,'__init__',side_effect=AssertionError('Runtime read regions')):
        before = np.array([tuple(v.co) for v in inflated(r).data.vertices])
        obj = find_geometry_mesh_scp_obj(bpy.context.scene,r.name,fiber.a_parent_id)
        obj.location.x += .25; bpy.context.view_layer.update()
        apply_fiber_node_attachments(r,bpy.context.scene,{f.id for f in r.af_vcp_system.fibers})
        BlenderScene(r,bpy.context.scene).refresh()
        after = np.array([tuple(v.co) for v in inflated(r).data.vertices])
    np.testing.assert_allclose(after[0]-before[0], [.25,0,0], atol=1e-6)


def repair_and_publish(test,r,directory,identity):
    operations = [dict(op="replace",path="/volume_presets/baseline/shape_checks/0/minimum/value",value=0),
                  dict(op="replace",path="/volume_presets/baseline/shape_checks/0/maximum/value",value=10)]
    params = dict(document_id=identity,expected_draft_revision=1,operations=operations)
    result = execute(request(r,"patch_draft",**params),r,bpy.context.scene,directory)
    validate(result,"protocol")
    test.assertEqual(result["status"],"success",result)
    test.assertFalse(result["published"])
    test.assertEqual(result["draft_revision"],2)
    result = execute(request(r,"publish_draft",document_id=identity,expected_draft_revision=2),r,bpy.context.scene,directory)
    validate(result,"protocol")
    test.assertTrue(result["published"],result)
    test.assertEqual(len(r.af_vcp_system.muscles),1)
