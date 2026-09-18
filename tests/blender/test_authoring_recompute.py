"""Public recompute dispatch, live status, replay and scope validation."""
import tempfile
import os
from unittest.mock import patch
from uuid import uuid4
import bpy
from mathutils import Vector
from _helpers import BlenderTestCase, root, scp_with_object
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.adapters.authoring import fiber_recompute as jobs
from anthroforge.app.authoring.api import execute
from anthroforge.core.authoring.schema import validate
from anthroforge.core.vcp.attachment_backend import capture_attachment_from_world
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization import fiber_refinement as runtime


def fixture():
    r = root(); owners = []
    for x in (0, 5):
        bpy.ops.mesh.primitive_cube_add(size=2, location=(x, 0, 0))
        owners.append(scp_with_object(r, 'Owner'+str(x), bpy.context.object))
    with suppress_vcp_prop_updates():
        f = r.af_vcp_system.fibers.add(); f.id = 'FIBER_RECOMPUTE'; f.node_count = 17; f.solver_version = 3
        f.a_parent_id, f.b_parent_id = (s.id for s in owners)
        f.a_attach_param = capture_attachment_from_world(r, bpy.context.scene, f.a_parent_id, Vector((1, 0, 0)))
        f.b_attach_param = capture_attachment_from_world(r, bpy.context.scene, f.b_parent_id, Vector((4, 0, 0)))
    return r, f


class AuthoringRecomputeTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        environment = patch.dict(os.environ, {'AF_FIBER_ENGINE': 'V3'}); environment.start(); self.addCleanup(environment.stop)
        self.r, self.f = fixture(); self.port = StaticScene(self.r, bpy.context.scene)
        self.port.initialize(); directory = tempfile.TemporaryDirectory()
        self.directory = directory.name; self.addCleanup(directory.cleanup)

    def request(self, op='fibers.recompute', **params):
        if op == 'fibers.recompute': params.setdefault('expected_scene_revision', self.port.capture_authoring()['revision'])
        return dict(version='0.4.0', message_type='request', request_id=str(uuid4()), op=op,
                    params=dict(scene_id=self.r.name, **params))

    def call(self, request):
        result = execute(request, self.r, bpy.context.scene, self.directory)
        validate(result, 'protocol')
        return result

    def test_native_run_and_live_poll_without_capture_or_restart(self):
        request = self.request(); started = self.call(request)
        self.assertEqual(started['status'], 'success', started)
        runtime.drain_fiber_refinements()
        poll = self.request('fibers.recompute_status', token=started['recompute']['token'])
        with patch('anthroforge.adapters.authoring.inventory.capture', side_effect=AssertionError('capture')):
            with patch.object(runtime, 'request_fiber_refinement_group', side_effect=AssertionError('restart')):
                done, replay = self.call(poll), self.call(request)
        self.assertTrue(done['recompute']['done'], done)
        self.assertEqual(done['recompute']['committed'], [self.f.id], done)
        self.assertTrue(replay['replayed']); self.assertEqual(done['recompute'], replay['recompute'])

    def test_stale_revision_and_missing_fiber_do_not_enqueue(self):
        with patch.object(runtime, 'request_fiber_refinement_group', side_effect=AssertionError('enqueue')):
            stale = self.call(self.request(expected_scene_revision='stale'))
            missing = self.call(self.request(fiber_ids=['absent']))
        self.assertEqual(stale['diagnostics'][0]['code'], 'STALE_SCENE_REVISION')
        self.assertEqual(missing['diagnostics'][0]['code'], 'FIBER_NOT_FOUND')

    def test_reused_request_payload_and_foreign_root_are_rejected(self):
        request = self.request(); started = self.call(request)
        changed = dict(request, params=dict(request['params'], cold_start=False))
        self.assertEqual(self.call(changed)['diagnostics'][0]['code'], 'REQUEST_ID_REUSED')
        other = bpy.data.objects.new('OtherRoot', None); bpy.context.scene.collection.objects.link(other)
        with self.assertRaisesRegex(Exception, 'Recompute job not found'):
            jobs.status(other, bpy.context.scene, started['recompute']['token'])

    def test_failure_is_terminal_and_does_not_claim_publication(self):
        with suppress_vcp_prop_updates(): self.f.b_attach_param = ''
        value = self.call(self.request())
        self.assertTrue(value['recompute']['done'], value)
        self.assertIn(self.f.id, value['recompute']['failures'])
        self.assertFalse(value['published']); self.assertEqual(value['status'], 'unresolved')
