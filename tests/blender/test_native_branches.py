import tempfile
from unittest.mock import patch
import numpy as np
import bpy
from _helpers import BlenderTestCase
from _branch_fixture import create_fixture
from anthroforge.app.use_cases import muscle_branch as use
from anthroforge.core.visualization.branched_surface_capture import capture_assembly
from anthroforge.core.visualization.muscle_numeric_runtime import _branched_request
from anthroforge.core.vcp.muscle_numeric import execute_muscle_batch
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.app.authoring.api import execute


class NativeBranchTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        self.root, self.muscle, self.connection, self.fibers = create_fixture()

    def test_native_capture_publish_and_protected_roots(self):
        request = _branched_request(self.root, bpy.context.scene, self.muscle)
        result = execute_muscle_batch((request,)).results[0]
        self.assertFalse(result.error, result.error)
        self.assertTrue(np.isfinite(result.inflated_vertices).all())
        self.assertGreater(len(result.faces), 100)
        self.assertEqual(len(self.fibers[1].mid_touches), 0)
        with self.assertRaisesRegex(ValueError, 'Remove'):
            use.detach_point(self.root, self.fibers[0].id, 1)

    def test_remove_preserves_sources_and_shared_points(self):
        counts = len(self.root.af_vcp_system.fibers), len(self.root.af_vcp_system.authored_points)
        original = self.fibers[0].mid_touches[0].point_id
        use.remove_branch(self.root, self.muscle.id, self.connection.id)
        self.assertEqual(counts, (len(self.root.af_vcp_system.fibers), len(self.root.af_vcp_system.authored_points)))
        self.assertEqual(self.fibers[2].a_point_id, original)
        self.assertEqual(use.muscle_surface(self.root, self.muscle).construction_mode, 'LOFT')
        self.assertAlmostEqual(self.muscle.inflation_max_value, .2)

    def test_profile_capture_uses_retained_sources_of_empty_branch_wrapper(self):
        from anthroforge.app.use_cases.muscle_profile import inspect, preview
        wrapper = use.muscle_surface(self.root, self.muscle)
        wrapper.fiber_refs.clear()
        target, state = inspect(self.root, bpy.context.scene, self.muscle.id)
        self.assertTrue(state['current'], state)
        self.assertEqual(len(state['base_revision']), 64)
        _, _, batch = preview(target, dict(mode='distributed', native=dict(inflation_max_value=.12)))
        self.assertFalse(batch.results[0].error)

    def test_profile_capture_rejects_stale_child_of_branch_wrapper(self):
        from anthroforge.app.use_cases.muscle_profile import inspect
        child = self.fibers[-1]
        proxy = next(o for o in bpy.context.scene.objects if o.get('af_fiber_proxy')
                     and o.get('af_fiber_id') == child.id and not o.get('af_fiber_mirror_proxy'))
        proxy['af_fiber_output_state'] = 'STALE'
        target, state = inspect(self.root, bpy.context.scene, self.muscle.id)
        self.assertFalse(state['current'])
        self.assertFalse(state['base_revision'])
        self.assertIn('PROFILE_BASE_NOT_CURRENT', state['reasons'][0])

    def test_transaction_failure_restores_graph_and_settings(self):
        from anthroforge.app.authoring.native_branches import _transaction
        from anthroforge.adapters.authoring.capture import native_records
        from anthroforge.core.authoring.errors import AuthoringError
        before = native_records(self.root)
        request = dict(op='muscles.branch_configure', params=dict(muscle_id=self.muscle.id,
            connection_id=self.connection.id, connector=dict(fullness=.12), inflation=dict(unknown_field=1)))
        with self.assertRaises(AuthoringError):
            _transaction(self.root, request)
        self.assertEqual(native_records(self.root), before)

    def test_viewport_shared_change_invalidates_exact_incident_fibers(self):
        from anthroforge.core.visualization.fiber_sync_runtime import _shared_bindings, _invalidate_shared_edit
        from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
        from unittest.mock import Mock
        fiber = self.fibers[0]
        before, dirty, sync = _shared_bindings(fiber), set(), Mock()
        with suppress_vcp_prop_updates():
            fiber.mid_touches[0].normal_offset = .03
        _invalidate_shared_edit(sync, fiber, before, dirty)
        self.assertEqual(dirty, {fiber.id, self.fibers[2].id})
        self.assertEqual(sync.clear_solver_cache.call_count, 2)

    def test_shared_endpoint_snap_uses_offset_and_largest_incident_radius(self):
        from anthroforge.core.visualization.fiber_sync_runtime import _endpoint_target
        from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
        from types import SimpleNamespace
        from mathutils import Vector
        with suppress_vcp_prop_updates():
            self.fibers[0].mid_touches[0].normal_offset = .06
            self.fibers[0].collision_radius = .02
        handle = SimpleNamespace(location=Vector((.75, -2, -.75)))
        with patch('anthroforge.core.visualization.fiber_sync_runtime.capture_attachment_target') as capture:
            _endpoint_target(None, self.root, bpy.context.scene, handle, None, self.fibers[2], 'A')
        self.assertAlmostEqual(capture.call_args.args[-2], .02)
        self.assertAlmostEqual(capture.call_args.args[-1], .06)

    def test_api_configure_replay_and_no_fiber_solve(self):
        port = StaticScene(self.root, bpy.context.scene)
        request = dict(version='0.4.0', message_type='request', request_id='configure', op='muscles.branch_configure',
            params=dict(scene_id=self.root.name, expected_scene_revision=port.capture_authoring()['revision'],
                        muscle_id=self.muscle.id, connection_id=self.connection.id, connector=dict(fullness=.07)))
        with tempfile.TemporaryDirectory() as directory:
            with patch('anthroforge.app.runtime_api.schedule_context') as schedule:
                result = execute(request, self.root, bpy.context.scene, directory)
                replay = execute(request, self.root, bpy.context.scene, directory)
        self.assertEqual(result['status'], 'success', result)
        self.assertTrue(replay['replayed'], replay)
        self.assertEqual(schedule.call_count, 1)
        self.assertEqual(schedule.call_args.kwargs['event_type'], 'MUSCLE_UPDATE')
