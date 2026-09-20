"""Exact native face bindings must survive edits without replacing qualified picks."""
import json
import tempfile
from unittest.mock import patch
import bpy
from _helpers import BlenderTestCase, scp_with_object
from _branch_fixture import create_fixture
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.adapters.authoring.capture import native_records
from anthroforge.app.authoring.api import execute


class RetainedPointTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        self.root, self.muscle, self.connection, self.fibers = create_fixture()
        self.identity = self.fibers[0].mid_touches[0].point_id
        point = next(p for p in self.root.af_vcp_system.authored_points if p.id == self.identity)
        self.binding = dict(parent_id=point.parent_id, attach_param=point.attach_param)

    def request(self, attachment=None, **values):
        params = dict(scene_id=self.root.name, expected_scene_revision=StaticScene(self.root,bpy.context.scene).capture_authoring()['revision'],
                      point_id=self.identity, attachment=self.binding if attachment is None else attachment, **values)
        return dict(version='0.4.0',message_type='request',request_id='retained',op='points.edit',params=params)

    def invoke(self, request):
        with tempfile.TemporaryDirectory() as directory:
            with patch('anthroforge.app.runtime_api.schedule_context'):
                return execute(request,self.root,bpy.context.scene,directory)

    def test_exact_binding_offset_shared_identity_and_replay(self):
        request=self.request(offset=.25)
        with tempfile.TemporaryDirectory() as directory:
            with patch('anthroforge.app.runtime_api.schedule_context') as schedule:
                result=execute(request,self.root,bpy.context.scene,directory)
                replay=execute(request,self.root,bpy.context.scene,directory)
        self.assertEqual(result['status'],'success',result)
        self.assertTrue(replay['replayed'],replay)
        point=next(p for p in self.root.af_vcp_system.authored_points if p.id == self.identity)
        self.assertEqual(point.attach_param,self.binding['attach_param'])
        self.assertAlmostEqual(point.normal_offset,.25)
        self.assertEqual(self.fibers[2].a_point_id,self.identity)
        self.assertEqual(schedule.call_count,1)

    def test_buried_final_offset_rejects_and_rolls_back(self):
        before=native_records(self.root); result=self.invoke(self.request(offset=-.1))
        self.assertEqual(result['status'],'unresolved',result)
        self.assertEqual(result['diagnostics'][0]['code'],'RETAINED_ATTACHMENT_UNQUALIFIED')
        self.assertEqual(native_records(self.root),before)

    def test_invalid_evaluated_triangle_rejects_and_rolls_back(self):
        binding=dict(self.binding); data=json.loads(binding['attach_param']); data['tri_vidx']=[0,1,7]
        binding['attach_param']=json.dumps(data); before=native_records(self.root)
        result=self.invoke(self.request(binding,offset=.2))
        self.assertEqual(result['status'],'unresolved',result)
        self.assertEqual(result['diagnostics'][0]['code'],'RETAINED_ATTACHMENT_TRIANGLE_INVALID')
        self.assertEqual(native_records(self.root),before)

    def test_buried_underlying_surface_rejects_even_with_clear_final_offset(self):
        bpy.ops.mesh.primitive_cube_add(size=1,location=(.75,-2,-.75))
        scp_with_object(self.root,'Occluding neighbor',bpy.context.object);bpy.context.view_layer.update()
        before=native_records(self.root);result=self.invoke(self.request(offset=.8))
        self.assertEqual(result['status'],'unresolved',result)
        self.assertEqual(result['diagnostics'][0]['code'],'RETAINED_ATTACHMENT_UNQUALIFIED')
        self.assertEqual(native_records(self.root),before)

    def test_physical_endpoint_offset_policy_is_preserved(self):
        self.identity=self.fibers[1].a_point_id;before=native_records(self.root)
        result=self.invoke(self.request(offset=.2))
        self.assertEqual(result['status'],'unresolved',result)
        self.assertEqual(native_records(self.root),before)

    def test_attachment_and_world_guess_are_mutually_exclusive(self):
        before=native_records(self.root);result=self.invoke(self.request(position=[0.,-2.,0.]))
        self.assertEqual(result['status'],'unresolved',result)
        self.assertEqual(native_records(self.root),before)

    def crease_binding(self):
        from anthroforge.core.vcp.attachment_backend import _parent_mesh, attachment_runtime
        from anthroforge.core.scp_runtime.surface import build_mesh_surface_data
        runtime=attachment_runtime(bpy.context.scene);obj=_parent_mesh(self.root,bpy.context.scene,self.binding['parent_id'])
        data=build_mesh_surface_data(obj,runtime['depsgraph'],runtime['surface_cache'])
        for triangle in data['triangles']:
            vertices=[data['verts_world'][i] for i in triangle]
            edge=[i for i,p in enumerate(vertices) if abs(p.x-2)<1e-6]
            if len(edge)==2 and all(abs(p.y+2)<1e-6 for p in vertices):
                weights=[.5 if i in edge else 0. for i in range(3)]
                raw=json.dumps(dict(mode='surface_param_v2',tri_vidx=list(map(int,triangle)),tri_weights=weights))
                return dict(parent_id=self.binding['parent_id'],attach_param=raw)
        raise AssertionError('Cube front crease triangle was not found')

    def test_crease_face_normal_and_raw_binding_are_retained(self):
        from anthroforge.core.vcp.attachment_backend import resolve_attachment_normal
        binding=self.crease_binding();result=self.invoke(self.request(binding,offset=.25))
        self.assertEqual(result['status'],'success',result)
        point=next(p for p in self.root.af_vcp_system.authored_points if p.id==self.identity)
        self.assertEqual(point.attach_param,binding['attach_param'])
        normal=resolve_attachment_normal(self.root,bpy.context.scene,point.parent_id,point.attach_param)
        self.assertLess(abs(normal.x)+abs(normal.z),1e-6)
        self.assertAlmostEqual(normal.y,-1.)

    def test_invalid_barycentric_weights_reject_and_roll_back(self):
        before=native_records(self.root);binding=dict(self.binding);data=json.loads(binding['attach_param'])
        data['tri_weights']=[-.1,.5,.6];binding['attach_param']=json.dumps(data)
        result=self.invoke(self.request(binding))
        self.assertEqual(result['status'],'unresolved',result)
        self.assertEqual(result['diagnostics'][0]['code'],'RETAINED_ATTACHMENT_WEIGHTS_INVALID')
        self.assertEqual(native_records(self.root),before)

    def test_linking_physical_endpoint_to_midpoint_does_not_allow_offset(self):
        request=self.request();request['op']='points.link'
        del request['params']['attachment'];request['params'].update(fiber_id=self.fibers[1].id,index=0)
        self.assertEqual(self.invoke(request)['status'],'success')
        before=native_records(self.root);request=self.request(offset=.2);request['request_id']='offset-linked'
        result=self.invoke(request)
        self.assertEqual(result['status'],'unresolved',result)
        self.assertEqual(native_records(self.root),before)

    def seed_runtime(self):
        from anthroforge.core.vcp.runtime_state import set_fiber_invalid_reason,set_fiber_recompute_status
        for fiber in self.fibers:
            set_fiber_invalid_reason(fiber,'Prior validation '+fiber.id)
            set_fiber_recompute_status(fiber,'INVALID_ATTACHMENT')
        for obj in bpy.context.scene.objects:
            if obj.get('af_fiber_proxy'):obj['af_fiber_output_state']='INVALID'

    def runtime_values(self):
        from anthroforge.core.vcp.runtime_state import fiber_invalid_reason,fiber_recompute_status
        fibers={f.id:(f.as_pointer(),fiber_recompute_status(f),fiber_invalid_reason(f)) for f in self.root.af_vcp_system.fibers}
        proxies={o.name:o.get('af_fiber_output_state') for o in bpy.context.scene.objects if o.get('af_fiber_proxy')}
        return fibers,proxies

    def test_notification_failure_restores_native_and_transient_state(self):
        request=self.request(offset=.25);self.seed_runtime()
        before=native_records(self.root);runtime=self.runtime_values()
        from anthroforge.core.visualization.fiber_refinement import _JOBS
        jobs=dict(_JOBS)
        with tempfile.TemporaryDirectory() as directory:
            with patch('anthroforge.app.runtime_api.schedule_context',side_effect=RuntimeError('Scheduling failed')):
                result=execute(request,self.root,bpy.context.scene,directory)
        self.assertEqual(result['status'],'unresolved',result)
        self.assertEqual(native_records(self.root),before)
        self.assertEqual(self.runtime_values(),runtime)
        self.assertEqual(_JOBS,jobs)
