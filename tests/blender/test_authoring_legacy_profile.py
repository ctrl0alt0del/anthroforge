"""Actual legacy preview, publication, rollback and persisted control state."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import bpy
import numpy as np
from _helpers import BlenderTestCase
from _profile_fixture import surface_only
from _branch_fixture import create_fixture
from test_authoring_native_profiles import call, inspect, request, create, fail_response
from anthroforge.app.use_cases.muscle_branch import muscle_surface
from anthroforge.adapters.authoring.capture import native_records
from anthroforge.core.authoring.storage import FileStore
from anthroforge.core.visualization.muscle_profile_publish import affected_objects
from anthroforge.core.vcp.fiber_solver import FiberSolver
from anthroforge.core.authoring.codec import encode
from anthroforge.app.authoring.native_profiles import _postcondition
from anthroforge.app.use_cases import muscle_profile as commands
from anthroforge.app.use_cases.fiber_surface_create import create_native_muscle
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization.muscle_sync import register_muscle_sync
from anthroforge.adapters.authoring.records import record


def payload(owner, directory, muscle, operation, identity, configuration):
    _, guards = inspect(owner, directory, dict(muscle_id=muscle.id), identity+'-state')
    target = dict(target=dict(muscle_id=muscle.id), include_geometry=True) if operation == 'profile_preview' else dict(muscle_id=muscle.id)
    return request(owner, operation, identity, configuration=configuration, **target, **guards)


def configuration(side=False):
    return dict(mode='control_point', native=dict(inflation_enabled=True, inflation_max_value=.25,
        inflation_ctrl_world=[.125, -2., -.25], inflation_falloff_radius=1.2, inflation_direction_depth=.3), surface_flip_normals=side)


def geometry(owner, muscle):
    return {obj.name: [[*v.co] for v in obj.data.vertices] for obj in affected_objects(owner, bpy.context.scene, muscle.id) if obj.type == 'MESH'}


def prior_receipt(owner, directory, muscle, command):
    store, key = FileStore(directory), [owner.name, command['request_id']]
    value = store.get('v04_profile_receipts', key)
    state, _ = inspect(owner, directory, dict(muscle_id=muscle.id), 'before-upgrade')
    value.update(version=1, postcondition=_postcondition(state['entities'][0], value['kind'], 1))
    store.put('v04_profile_receipts', key, value)
    muscle['af_authoring_profile_receipt'] = encode(value)


def select_child(owner, muscle, surface):
    with suppress_vcp_prop_updates():
        owner.af_vcp_system.active_vcp_type = 'MUSCLE'
        owner.af_vcp_system.active_vcp_id = muscle.id
        surface.active_branch_index = 0
    register_muscle_sync().sync_root_to_scene(owner, bpy.context.scene)


def shared_fixture():
    owner, muscle, connection, _ = create_fixture()
    surface = muscle_surface(owner, muscle)
    ordinary = create_native_muscle(owner, bpy.context.scene, surface.main_surface_id, 'Shared main')
    select_child(owner, muscle, surface)
    with suppress_vcp_prop_updates():
        connection.settings.inflation_mode = 'CTRL_POINT'
        connection.settings.inflation_ctrl_world = (0., 0., 0.)
        connection.settings.inflation_ctrl_initialized = False
    return owner, muscle, connection, ordinary


def check_parity(test, owner, muscle, directory, config):
    before = native_records(owner), geometry(owner, muscle)
    preview = call(owner, directory, payload(owner, directory, muscle, 'profile_preview', 'peek', config))
    test.assertEqual(preview['status'], 'success', preview)
    test.assertEqual(before, (native_records(owner), geometry(owner, muscle)))
    proposed = json.loads(Path(preview['assets'][0]['path']).read_text())
    command = payload(owner, directory, muscle, 'profile_configure', 'write', config)
    result = call(owner, directory, command)
    test.assertTrue(result['published'], result)
    test.assertTrue(call(owner, directory, command)['replayed'])
    obj = next(o for o in bpy.context.scene.objects if o.get('af_muscle_id') == muscle.id and o.get('af_muscle_surface') == 'INFL')
    np.testing.assert_allclose([v.co[:] for v in obj.data.vertices], proposed['inflated'], atol=2e-6)
    test.assertTrue(muscle.inflation_ctrl_initialized)
    np.testing.assert_allclose(muscle.inflation_ctrl_world, config['native']['inflation_ctrl_world'], atol=1e-7)
    return command


class LegacyProfileTests(BlenderTestCase):
    def test_legacy_fiber_side_has_one_value_for_preview_and_regeneration(self):
        owner, surface = surface_only()
        with TemporaryDirectory() as directory:
            create(owner, surface, directory)
            muscle = owner.af_vcp_system.muscles[0]
            with suppress_vcp_prop_updates():
                muscle.surface_source_mode = 'LEGACY_FIBERS'
                for ref in surface.fiber_refs: muscle.fiber_refs.add().fiber_id = ref.fiber_id
            config = configuration(); config.pop('surface_flip_normals'); config['native']['flip_normals'] = True
            check_parity(self, owner, muscle, directory, config)
            target, _ = commands.inspect(owner, bpy.context.scene, muscle.id)
            with self.assertRaisesRegex(ValueError, 'PROFILE_SIDE_CONFLICT'):
                commands.preview(target, dict(config, surface_flip_normals=False))

    def test_ordinary_native_side_controls_displacement_without_moving_base(self):
        owner, surface = surface_only()
        with TemporaryDirectory() as directory:
            create(owner, surface, directory)
            target, _ = commands.inspect(owner, bpy.context.scene, owner.af_vcp_system.muscles[0].id)
            left = commands.preview(target, dict(mode='distributed', native=dict(flip_normals=False)))[2].results[0]
            right = commands.preview(target, dict(mode='distributed', native=dict(flip_normals=True)))[2].results[0]
            np.testing.assert_array_equal(left.base_vertices, right.base_vertices)
            self.assertGreater(float(np.max(np.abs(left.inflated_vertices-right.inflated_vertices))), .001)

    def test_branch_rejects_ignored_per_part_side_and_inspector_omits_it(self):
        owner, muscle, _, _ = create_fixture()
        target, state = commands.inspect(owner, bpy.context.scene, muscle.id)
        self.assertNotIn('flip_normals', state['legacy_configuration']['native'])
        with self.assertRaisesRegex(ValueError, 'PROFILE_SIDE_UNSUPPORTED'):
            commands.preview(target, dict(mode='distributed', native=dict(flip_normals=True)))

    def test_uninitialized_inspector_roundtrip_preserves_automatic_control(self):
        owner, muscle, _, _ = create_fixture()
        select_child(owner, muscle, muscle_surface(owner, muscle))
        commands.configure(owner, bpy.context.scene, muscle.id, dict(mode='control_point', native=dict(inflation_max_value=.3)))
        target, state = commands.inspect(owner, bpy.context.scene, muscle.id)
        self.assertFalse(muscle.inflation_ctrl_initialized)
        self.assertNotIn('inflation_ctrl_world', state['legacy_configuration']['native'])
        _, _, expected = commands.preview(target, dict(mode='control_point'))
        _, _, actual = commands.preview(target, state['legacy_configuration'])
        np.testing.assert_array_equal(expected.results[0].inflated_vertices, actual.results[0].inflated_vertices)

    def test_transitive_assembly_side_publication_failure_restores_child(self):
        owner, muscle, connection, ordinary = shared_fixture()
        before = record(connection.settings), geometry(owner, muscle)
        source = next(s for s in owner.af_vcp_system.fiber_surfaces if s.id == ordinary.fiber_surface_id)
        with patch.object(commands, 'publish', side_effect=ValueError('injected publication failure')):
            with self.assertRaisesRegex(ValueError, 'injected publication failure'):
                commands.configure(owner, bpy.context.scene, ordinary.id, configuration(not source.flip_normals))
        self.assertEqual(before, (record(connection.settings), geometry(owner, muscle)))

    def test_pre_extension_receipt_still_replays_unchanged_configuration(self):
        owner, surface = surface_only()
        with TemporaryDirectory() as directory:
            create(owner, surface, directory)
            muscle = owner.af_vcp_system.muscles[0]
            command = payload(owner, directory, muscle, 'profile_configure', 'restore-mode', dict(mode='distributed'))
            self.assertTrue(call(owner, directory, command)['published'])
            prior_receipt(owner, directory, muscle, command)
            self.assertTrue(call(owner, directory, command)['replayed'])

    def test_missing_surface_remains_inspectable(self):
        owner, surface = surface_only()
        with TemporaryDirectory() as directory:
            create(owner, surface, directory)
            muscle = owner.af_vcp_system.muscles[0]
            owner.af_vcp_system.fiber_surfaces.clear()
            result, _ = inspect(owner, directory, dict(muscle_id=muscle.id), 'missing')
            self.assertFalse(result['entities'][0]['current'])
            self.assertNotIn('surface_flip_normals', result['entities'][0]['legacy_configuration'])

    def test_ordinary_preview_explicit_control_side_and_replay(self):
        owner, surface = surface_only()
        with TemporaryDirectory() as directory:
            create(owner, surface, directory)
            muscle = owner.af_vcp_system.muscles[0]
            with patch.object(FiberSolver, 'solve_points', side_effect=AssertionError('unexpected fiber solve')):
                command = check_parity(self, owner, muscle, directory, configuration(not surface.flip_normals))
            muscle.inflation_max_value = .5
            self.assertEqual(call(owner, directory, command)['diagnostics'][0]['code'], 'STALE_PROFILE_RECEIPT')

    def test_branched_preview_complete_assembly_matches_publication(self):
        owner, muscle, _, _ = create_fixture()
        surface = muscle_surface(owner, muscle)
        with TemporaryDirectory() as directory:
            with patch.object(FiberSolver, 'solve_points', side_effect=AssertionError('unexpected fiber solve')):
                check_parity(self, owner, muscle, directory, configuration(not surface.flip_normals))

    def test_journal_failure_restores_side_controls_and_all_meshes(self):
        owner, muscle, _, _ = create_fixture()
        surface = muscle_surface(owner, muscle)
        with TemporaryDirectory() as directory:
            command = payload(owner, directory, muscle, 'profile_configure', 'fail', configuration(not surface.flip_normals))
            before = native_records(owner), geometry(owner, muscle), bool(surface.flip_normals)
            with patch.object(FileStore, 'put', fail_response(FileStore.put)):
                result = call(owner, directory, command)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(before, (native_records(owner), geometry(owner, muscle), bool(surface.flip_normals)))
