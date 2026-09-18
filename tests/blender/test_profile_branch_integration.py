"""Native branch settings, authoring receipts and ordinary profiles coexist."""
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase
from _branch_fixture import create_fixture
from test_muscle_section_profile import mesh
from test_authoring_native_profiles import call, inspect, request, base_fingerprint
from anthroforge.app.use_cases import muscle_branch as branches
from anthroforge.app.use_cases.fiber_surface_create import create_native_muscle
from anthroforge.adapters.authoring.capture import native_records
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.core.authoring.profile_config import wire
from anthroforge.core.vcp.muscle_section_profile import reset_profile
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.vcp.fiber_solver import FiberSolver
from anthroforge.core.visualization.muscle_sync import register_muscle_sync
from anthroforge.core.visualization.muscle_profile_publish import affected_objects


class ModeLayout:
    def __init__(self):
        self.enabled, self.rows, self.operations = True, [], []

    def row(self):
        child = ModeLayout(); self.rows.append(child)
        return child

    def operator(self, *args, **kwargs):
        value = SimpleNamespace(); self.operations.append(value)
        return value

    def label(self, **kwargs):
        pass


class ProfileBranchIntegrationTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        self.root, self.muscle, self.connection, self.fibers = create_fixture()
        self.scene, self.sync = bpy.context.scene, register_muscle_sync()
        self.surface = branches.muscle_surface(self.root, self.muscle)
        self.profile = create_native_muscle(self.root, self.scene, self.surface.main_surface_id,
            'Ordinary profile', wire(reset_profile(.15)))
        with suppress_vcp_prop_updates():
            self.root.af_vcp_system.active_vcp_type = 'MUSCLE'
            self.root.af_vcp_system.active_vcp_id = self.muscle.id
        self.sync.sync_root_to_scene(self.root, self.scene)
        directory = TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.directory = directory.name

    def _call(self, payload):
        return call(self.root, self.directory, payload)

    def _request(self, operation, identity, **params):
        return dict(dsl='anthroforge.authoring.protocol', version='0.4.0', message_type='request', request_id=identity, op=operation,
                    params=dict(scene_id=self.root.name, **params))

    def _profile_request(self, configuration, identity):
        _, guards = inspect(self.root, self.directory, dict(muscle_id=self.muscle.id), identity+'-inspect')
        return request(self.root, 'profile_configure', identity, muscle_id=self.muscle.id,
                       configuration=configuration, **guards)

    def _control(self):
        with suppress_vcp_prop_updates():
            self.connection.settings.inflation_mode = 'CTRL_POINT'
        with patch.object(self.sync, '_selected_muscle_id', return_value=self.muscle.id):
            self.sync.sync_root_to_scene(self.root, self.scene, {self.muscle.id})
        collection = self.sync._get_vis_collection(self.scene)
        self.assertIsNotNone(self.sync._find_inflation_ctrl(collection, self.root.name, self.muscle.id))

    def _direct_profile(self, settings):
        self._control()
        original = mesh(self.root, self.profile).copy()
        with patch.object(FiberSolver, 'solve_points', side_effect=AssertionError('solve')):
            with patch.object(self.sync, '_collect_points_with_fallback', side_effect=AssertionError('fallback')):
                settings.inflation_mode = 'SECTION_PROFILE'
                self.sync.sync_root_to_scene(self.root, self.scene)
        self.assertIn('PROFILE_DOMAIN_UNSUPPORTED', self.muscle['_af_rt_section_profile_error'])
        self.assertTrue(all(obj.get('af_muscle_output_state') == 'INVALID'
            for obj in affected_objects(self.root, self.scene, self.muscle.id)))
        self.assertEqual(len(mesh(self.root, self.muscle)), 0)
        self.assertFalse(any(obj.get('af_muscle_inflation_ctrl') for obj in affected_objects(self.root, self.scene, self.muscle.id)))
        np.testing.assert_array_equal(mesh(self.root, self.profile), original)

    def test_direct_main_profile_clears_only_branch_output_without_solving(self):
        self._direct_profile(self.muscle)

    def test_direct_child_profile_clears_only_branch_output_and_recovers(self):
        self._direct_profile(self.connection.settings)
        self.connection.settings.inflation_mode = 'DISTRIBUTED'
        self.sync.sync_root_to_scene(self.root, self.scene, {self.muscle.id})
        self.assertGreater(len(mesh(self.root, self.muscle)), 100)
        self.assertEqual(self.muscle['_af_rt_section_profile_error'], '')

    def test_mixed_refresh_keeps_branch_geometry_and_source_ownership(self):
        source = next(s for s in self.root.af_vcp_system.fiber_surfaces if s.id == self.surface.main_surface_id)
        fingerprint, original = base_fingerprint(self.root, source), mesh(self.root, self.muscle).copy()
        profile_before = mesh(self.root, self.profile).copy()
        with patch.object(FiberSolver, 'solve_points', side_effect=AssertionError('solve')):
            self.profile.section_roundness = 2
            self.sync.sync_root_to_scene(self.root, self.scene)
        np.testing.assert_array_equal(mesh(self.root, self.muscle), original)
        self.assertFalse(np.array_equal(mesh(self.root, self.profile), profile_before))
        self.assertEqual(base_fingerprint(self.root, source), fingerprint)
        proxies = affected_objects(self.root, self.scene, self.muscle.id)
        self.assertTrue(all(o['af_muscle_numeric_backend'] == 'NATIVE+NUMPY_SECTION_PROFILE' for o in proxies))

    def test_mode_menu_targets_selected_branch_and_disables_profile(self):
        from anthroforge.ui.panels.muscle_profile import draw_mode_options
        layout = ModeLayout()
        with patch('anthroforge.operators.muscle_profile._muscle', return_value=(self.root, self.muscle)):
            draw_mode_options(layout, bpy.context)
        self.assertEqual([r.enabled for r in layout.rows], [True, True, False])
        self.assertTrue(all(r.operations[0].branch_id == self.connection.id for r in layout.rows))
        original = self.muscle.inflation_mode
        result = bpy.ops.af.muscle_profile_mode(muscle_id=self.muscle.id, branch_id=self.connection.id, mode='control_point')
        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(self.connection.settings.inflation_mode, 'CTRL_POINT')
        self.assertEqual(self.muscle.inflation_mode, original)

    def test_unsupported_mode_operators_leave_main_and_child_settings_unchanged(self):
        original = native_records(self.root)
        for branch_id in ('', self.connection.id):
            with self.assertRaisesRegex(RuntimeError, 'PROFILE_DOMAIN_UNSUPPORTED'):
                bpy.ops.af.muscle_profile_mode(muscle_id=self.muscle.id, branch_id=branch_id, mode='section_profile')
            self.assertEqual(native_records(self.root), original)

    def test_adding_branch_to_profile_requires_explicit_legacy_switch(self):
        original = native_records(self.root)
        with self.assertRaisesRegex(ValueError, 'PROFILE_DOMAIN_UNSUPPORTED'):
            branches.add_branch(self.root, self.profile.id, self.connection.surface_id, self.fibers[0].id,
                                [p.point_id for p in self.fibers[0].mid_touches])
        self.assertEqual(native_records(self.root), original)

    def test_authoring_inspect_has_guards_and_rejects_main_profile(self):
        original = native_records(self.root)
        inspected, _ = inspect(self.root, self.directory, dict(muscle_id=self.muscle.id))
        state = inspected['entities'][0]
        self.assertTrue(state['current']); self.assertTrue(state['base_revision']); self.assertFalse(state['eligible'])
        result = self._call(self._profile_request(wire(reset_profile(.3)), 'main-profile'))
        self.assertEqual(result['diagnostics'][0]['code'], 'PROFILE_DOMAIN_UNSUPPORTED')
        self.assertEqual(native_records(self.root), original)

    def test_authoring_child_profile_rejected_with_transactional_settings(self):
        original = native_records(self.root)
        payload = self._request('muscles.branch_configure', 'child-profile', muscle_id=self.muscle.id,
            connection_id=self.connection.id, expected_scene_revision=StaticScene(self.root, self.scene).capture_authoring()['revision'],
            connector=dict(fullness=.15), inflation=dict(inflation_mode='SECTION_PROFILE'))
        result = self._call(payload)
        self.assertEqual(result['diagnostics'][0]['code'], 'PROFILE_DOMAIN_UNSUPPORTED')
        self.assertEqual(native_records(self.root), original)

    def test_branched_legacy_configuration_preserves_control_and_replays_live(self):
        with suppress_vcp_prop_updates():
            self.muscle.inflation_ctrl_world = (.125, -2., -.25)
            self.muscle.inflation_ctrl_initialized = True
        original = tuple(self.muscle.inflation_ctrl_world)
        payload = self._profile_request(dict(mode='control_point'), 'legacy-main')
        with patch.object(FiberSolver, 'solve_points', side_effect=AssertionError('solve')):
            result, replay = self._call(payload), self._call(payload)
        self.assertTrue(result['published'], result); self.assertTrue(replay['replayed'], replay)
        self.assertEqual(tuple(self.muscle.inflation_ctrl_world), original)
        self.assertGreater(len(mesh(self.root, self.muscle)), 100)
        self.muscle.flip_normals = not self.muscle.flip_normals
        self.assertEqual(self._call(payload)['diagnostics'][0]['code'], 'STALE_PROFILE_RECEIPT')

    def test_profile_and_native_operations_share_request_identity(self):
        profile = self._request('muscles.profile_inspect', 'profile-id', target=dict(muscle_id=self.profile.id))
        points = self._request('points.inspect', 'points-id')
        self.assertEqual(self._call(profile)['status'], 'success')
        self.assertEqual(self._call(dict(points, request_id='profile-id'))['diagnostics'][0]['code'], 'REQUEST_ID_REUSED')
        self.assertEqual(self._call(points)['status'], 'success')
        self.assertEqual(self._call(dict(profile, request_id='points-id'))['diagnostics'][0]['code'], 'REQUEST_ID_REUSED')
        recompute = self._request('fibers.recompute', 'profile-id', expected_scene_revision='unused')
        with patch('anthroforge.adapters.authoring.fiber_recompute.start', side_effect=AssertionError('enqueue')):
            self.assertEqual(self._call(recompute)['diagnostics'][0]['code'], 'REQUEST_ID_REUSED')

    def test_invalid_child_profile_numbers_remain_inspectable(self):
        with suppress_vcp_prop_updates():
            self.connection.settings.section_roundness = float('nan')
        self.connection.settings.inflation_mode = 'SECTION_PROFILE'
        result, _ = inspect(self.root, self.directory, dict(muscle_id=self.muscle.id))
        self.assertFalse(result['entities'][0]['eligible'])
        self.assertIn('PROFILE_DOMAIN_UNSUPPORTED', self.muscle['_af_rt_section_profile_error'])
