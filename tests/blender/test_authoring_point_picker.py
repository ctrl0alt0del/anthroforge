"""Snapping uses native attachments on evaluated geometry, with no authoring edits."""
import tempfile
from uuid import uuid4
from mathutils import Vector
import bpy
import numpy as np
from _helpers import BlenderTestCase, root, scp_with_object
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.adapters.authoring.attachments import capture
from anthroforge.app.authoring.api import execute
from anthroforge.core.authoring.schema import validate
from anthroforge.core.vcp import attachment_backend as backend


def cube(r, location=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=2, location=location)
    obj = bpy.context.object
    scp_with_object(r, obj.name, obj)
    return obj


class SurfacePointPickerTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        self.root = root()
        self.obj = cube(self.root)
        self.scene = StaticScene(self.root, bpy.context.scene)
        self.inventory = self.scene.initialize()
        self.owner = self.inventory['instances'][0]['instance_id']
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.directory = folder.name

    def request(self, points, **params):
        values = dict(scene_id=self.root.name, instance_id=self.owner, points=points,
                      expected_scene_revision=self.scene.capture_authoring()['revision'])
        values.update(params)
        return dict(version='0.4.0', message_type='request', request_id=str(uuid4()), op='anatomy.snap_points', params=values)

    def execute(self, request):
        result = execute(request, self.root, bpy.context.scene, self.directory)
        validate(result, 'protocol')
        return result

    def test_inside_and_outside_guesses_match_endpoint_snapping(self):
        points = [[.2, .1, .9], [.2, .1, 1.4]]
        result = self.execute(self.request(points))
        self.assertEqual(result['status'], 'success', result)
        for guess, hit in zip(points, result['hits']):
            raw = backend.capture_attachment_from_world(self.root, bpy.context.scene, self.owner, Vector(guess))
            self.assertEqual(hit['attachment']['attach_param'], raw)
            self.assertEqual(hit['attachment']['parent_id'], self.obj['af_scp_id'])
            np.testing.assert_allclose(hit['point'], [.2, .1, 1], atol=1e-6)
            self.assertEqual(capture(self.root, bpy.context.scene, hit['anchor']), raw)
        self.assertEqual(self.inventory['revision'], self.scene.capture_authoring()['revision'])
        self.assertFalse(result['published'])
        self.assertEqual(len(self.root.af_vcp_system.fibers), 0)

    def test_current_modifier_and_nonuniform_reflected_transform(self):
        self.obj.scale = (-2, 3, .5)
        self.obj.location = (4, 0, 0)
        modifier = self.obj.modifiers.new('Evaluated surface', 'DISPLACE')
        modifier.strength = .2
        result = self.execute(self.request([[4.2, .1, 1]]))
        self.assertEqual(result['status'], 'success', result)
        hit = result['hits'][0]
        self.assertGreater(hit['point'][2], .5)
        self.assertGreater(hit['normal'][2], .99)
        self.assertLess(hit['native_normal'][2], -.99)
        self.assertEqual(capture(self.root, bpy.context.scene, hit['anchor']), hit['attachment']['attach_param'])
        resolved = backend.resolve_attachment_world(self.root, bpy.context.scene, self.owner, hit['attachment']['attach_param'])
        np.testing.assert_array_equal(hit['point'], resolved)

    def test_blocked_closest_point_has_no_usable_attachment(self):
        blocker = cube(self.root, (0, 0, 1.5))
        data = self.scene.initialize()
        blocker_id = next(r['instance_id'] for r in data['instances'] if r['locator'] == blocker.name)
        result = self.execute(self.request([[.2, .1, .9], [.2, .1, -1.1]]))
        self.assertEqual(result['status'], 'unresolved', result)
        bad, good = result['hits']
        self.assertFalse(bad['valid'])
        self.assertTrue(good['valid'])
        self.assertTrue(any(r['blocker_id'] == blocker_id and r['contained'] for r in bad['blockers']))
        self.assertNotIn('attachment', bad)
        self.assertNotIn('anchor', bad)
        np.testing.assert_allclose(bad['point'], [.2, .1, 1], atol=1e-6)

    def test_distance_limit_preserves_nearest_point_for_review(self):
        result = self.execute(self.request([[.2, .1, 4]], max_distance=.1))
        self.assertEqual(result['status'], 'unresolved', result)
        hit = result['hits'][0]
        self.assertAlmostEqual(hit['snap_distance'], 3)
        self.assertEqual(hit['diagnostics'][0]['code'], 'SNAP_DISTANCE_EXCEEDED')
        self.assertNotIn('attachment', hit)

    def test_replaying_after_geometry_edit_rejects_stale_attachment(self):
        request = self.request([[.2, .1, 1.1]])
        self.assertEqual(self.execute(request)['status'], 'success')
        self.assertTrue(self.execute(request)['replayed'])
        self.obj.data.vertices[0].co.z -= .2
        self.obj.data.update()
        result = self.execute(request)
        self.assertEqual(result['status'], 'unresolved', result)
        self.assertEqual(result['diagnostics'][0]['code'], 'STALE_SCENE_REVISION')

    def test_missing_owner_never_falls_back_to_another_scp(self):
        result = self.execute(self.request([[0, 0, 0]], instance_id='AFI_missing'))
        self.assertEqual(result['status'], 'unresolved', result)
        self.assertEqual(result['diagnostics'][0]['code'], 'INSTANCE_NOT_FOUND')

    def test_payloads_resolve_as_native_endpoints_and_midpoints(self):
        from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
        from anthroforge.core.visualization.fiber_sync_helpers import endpoint_world, touch_world
        hits = self.execute(self.request([[.2, .1, 1.1], [.4, .2, 1.1]]))['hits']
        with suppress_vcp_prop_updates():
            fiber = self.root.af_vcp_system.fibers.add()
            fiber.id = 'FIBER_1'
            fiber.a_parent_id, fiber.a_attach_param = hits[0]['attachment']['parent_id'], hits[0]['attachment']['attach_param']
            touch = fiber.mid_touches.add()
            touch.parent_id, touch.attach_param, touch.normal_offset = hits[1]['attachment']['parent_id'], hits[1]['attachment']['attach_param'], 0
        runtime = backend.attachment_runtime(bpy.context.scene)
        first = endpoint_world(self.root, bpy.context.scene, runtime, fiber.a_parent_id, fiber.a_attach_param)
        middle = touch_world(self.root, bpy.context.scene, runtime, touch)
        np.testing.assert_array_equal(first, hits[0]['point'])
        np.testing.assert_array_equal(middle, hits[1]['point'])

    def test_native_refinement_accepts_picker_owners_and_commits(self):
        from unittest.mock import patch
        import os
        from anthroforge.core.visualization.fiber_refinement import request_fiber_refinement_group, drain_fiber_refinements, fiber_refinement_group_state
        hits = self.execute(self.request([[.1, .1, 1.1], [.3, .1, 1.1], [.6, .1, 1.1]]))['hits']
        fiber = native_fiber(self.root, hits)
        with patch.dict(os.environ, {'AF_FIBER_ENGINE': 'V3'}):
            token = request_fiber_refinement_group(self.root, bpy.context.scene, [fiber.id])
            self.assertTrue(drain_fiber_refinements())
        state = fiber_refinement_group_state(token)
        self.assertEqual(state['failures'], {}, state)
        self.assertEqual(state['committed'], (fiber.id,))


def native_fiber(root, hits):
    from anthroforge.app.use_cases.fiber_create import _new_fiber
    from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
    a, mid, b = [hit['attachment'] for hit in hits]
    with suppress_vcp_prop_updates():
        return _new_fiber(root, a['parent_id'], b['parent_id'], a['attach_param'], b['attach_param'], [(mid['parent_id'], mid['attach_param'])])
