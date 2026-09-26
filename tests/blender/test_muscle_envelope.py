"""Envelope capture, publication, controls, persistence and compatibility."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase
from test_muscle_section_profile import fixture, mesh
from anthroforge.app.use_cases import muscle_envelope as commands
from anthroforge.core.authoring.envelope_config import configuration
from anthroforge.core.visualization.muscle_sync import register_muscle_sync


class MuscleEnvelopeTests(BlenderTestCase):
    def test_control_gizmo_targets_secondary_only(self):
        from anthroforge.core.visualization.branch_control import control_part
        root, _, muscle = fixture(False); muscle.envelope_sides = 'BOTH_SIDES'
        muscle.envelope_edit_side = 'B'
        control = next(o for o in bpy.context.scene.objects if o.get('af_muscle_inflation_ctrl'))
        self.assertEqual(control.get('af_inflation_side'), 'B')
        self.assertEqual(control_part(root, muscle, control), muscle.inflation_secondary)
        self.assertTrue(muscle.inflation_secondary.inflation_ctrl_initialized)

    def test_branched_opposite_sides_have_same_base_and_seams(self):
        from dataclasses import replace
        from test_branched_inflation import fixture as assembly_fixture
        from test_muscle_numeric_backends import _spec
        from anthroforge.core.vcp.branched_numeric import BranchedMuscleRequest
        from anthroforge.core.vcp.muscle_envelope import MuscleEnvelopeSpec
        from anthroforge.core.vcp.muscle_numeric import execute_muscle_batch
        specs = (_spec('DISTRIBUTED'),)*2
        request = BranchedMuscleRequest('M', assembly_fixture(), specs, envelope=MuscleEnvelopeSpec(specs))
        result = execute_muscle_batch((request,)).results[0]
        self.assertEqual(result.error, '')
        self.assertGreater(len(result.inflated_faces), len(result.faces))
        self.assertEqual(result.side_a.shape, result.side_b.shape)

    def test_authoring_preview_and_configure(self):
        from uuid import uuid4
        from anthroforge.app.authoring.api import execute
        root, _, muscle = fixture(); target = dict(muscle_id=muscle.id)
        with TemporaryDirectory() as journal:
            call = lambda op, **p: execute(dict(dsl='anthroforge.authoring.protocol', version='0.4.0', message_type='request',
                request_id=str(uuid4()), op='muscles.inflation_'+op, params=dict(scene_id=root.name, **p)), root, bpy.context.scene, journal)
            state = call('inspect', target=target); self.assertEqual(state['status'], 'success', state)
            row = state['entities'][0]; config = row['configuration']; config['sides'] = 'both'
            guards = dict(expected_scene_revision=state['scene_revision'], expected_base_revision=row['base_revision'], expected_configuration_revision=row['configuration_revision'])
            preview = call('preview', target=target, configuration=config, include_geometry=True, **guards)
            self.assertEqual(preview['status'], 'success', preview)
            result = call('configure', muscle_id=muscle.id, configuration=config, **guards)
            self.assertEqual(result['status'], 'success', result)

    def test_activate_preserve_base_and_primary(self):
        root, surface, muscle = fixture()
        base, primary = mesh(root, muscle, 'BASE').copy(), mesh(root, muscle).copy()
        value = configuration(root, muscle); value['sides'] = 'both'
        target, _ = commands.inspect(root, bpy.context.scene, muscle.id)
        _, _, batch = commands.preview(target, value)
        np.testing.assert_allclose(batch.results[0].side_a, primary, atol=1e-7)
        commands.configure(root, bpy.context.scene, muscle.id, value)
        np.testing.assert_array_equal(mesh(root, muscle, 'BASE'), base)
        self.assertGreater(len(mesh(root, muscle)), len(primary))

    def test_direct_toggle_and_secondary_edit(self):
        root, _, muscle = fixture(); muscle.envelope_sides = 'BOTH_SIDES'
        self.assertTrue(muscle.inflation_secondary.initialized)
        self.assertTrue(len(mesh(root, muscle)))
        before = mesh(root, muscle).copy(); muscle.inflation_secondary.section_depths = (.01, .02, .02, .01)
        self.assertFalse(np.array_equal(mesh(root, muscle), before))
        self.assertTrue(muscle.envelope_version == 1)

    def test_save_reload_preserves_both_sides(self):
        root, _, muscle = fixture(); muscle.envelope_sides = 'BOTH_SIDES'
        identity, root_name = muscle.id, root.name
        before = mesh(root, muscle).copy(); config = configuration(root, muscle)
        with TemporaryDirectory() as directory:
            path = str(Path(directory)/'envelope.blend'); bpy.ops.wm.save_as_mainfile(filepath=path)
            bpy.ops.wm.open_mainfile(filepath=path)
            root = bpy.data.objects[root_name]; muscle = next(m for m in root.af_vcp_system.muscles if m.id == identity)
            register_muscle_sync().sync_root_to_scene(root, bpy.context.scene, {identity})
            self.assertEqual(configuration(root, muscle), config)
            np.testing.assert_array_equal(mesh(root, muscle), before)

    def test_transaction_rolls_back_both_sides(self):
        root, _, muscle = fixture(); muscle.envelope_sides = 'BOTH_SIDES'
        old = configuration(root, muscle); value = configuration(root, muscle)
        value['parts'][0]['b']['parameters']['depths'][1]['value'] = .4
        with patch.object(commands, 'publish', side_effect=ValueError('failed')):
            with self.assertRaises(ValueError): commands.configure(root, bpy.context.scene, muscle.id, value)
        self.assertEqual(configuration(root, muscle), old)

    def test_old_profile_mutation_rejects_both_sides(self):
        from anthroforge.app.use_cases import muscle_profile
        root, _, muscle = fixture(); muscle.envelope_sides = 'BOTH_SIDES'
        with self.assertRaisesRegex(ValueError, 'ENVELOPE_API_REQUIRED'):
            muscle_profile.configure(root, bpy.context.scene, muscle.id, {'mode': 'distributed'})


class EnvelopeLifecycleTests(BlenderTestCase):
    def test_copy_banks_modes_scale_and_no_solver(self):
        from anthroforge.core.vcp.fiber_solver import FiberSolver
        root, _, muscle = fixture(); muscle.envelope_sides = 'BOTH_SIDES'
        muscle.inflation_falloff_radius = 3.1; muscle.envelope_edit_side = 'B'
        with patch.object(FiberSolver, 'solve_points', side_effect=AssertionError('inflation solved fiber')):
            self.assertEqual(bpy.ops.af.muscle_envelope_action(muscle_id=muscle.id, action='COPY_A_B'), {'FINISHED'})
            self.assertAlmostEqual(muscle.inflation_secondary.inflation_falloff_radius, 3.1, places=5)
            self.assertEqual(bpy.ops.af.muscle_envelope_action(muscle_id=muscle.id, action='SCALE_PROFILE', factor=.5), {'FINISHED'})
            self.assertAlmostEqual(muscle.inflation_secondary.section_depths[1], muscle.section_depths[1]*.5)
            self.assertEqual(bpy.ops.af.muscle_envelope_mode(muscle_id=muscle.id, mode='DISTRIBUTED'), {'FINISHED'})
            self.assertEqual(bpy.ops.af.muscle_envelope_mode(muscle_id=muscle.id, mode='SECTION_PROFILE'), {'FINISHED'})
            self.assertAlmostEqual(muscle.inflation_secondary.section_depths[1], muscle.section_depths[1]*.5)

    def test_scaled_import_both_banks_and_independent_identity(self):
        from anthroforge.core.importing.rna import scalar_dict, apply_scalar_dict
        from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
        root, _, muscle = fixture(); muscle.envelope_sides = 'BOTH_SIDES'
        muscle.inflation_secondary.inflation_max_value = .12
        with suppress_vcp_prop_updates():
            clone = root.af_vcp_system.muscles.add(); apply_scalar_dict(clone, scalar_dict(muscle), geometry_scale=2)
            clone.id = 'MUSCLE_COPY'; clone.inflation_secondary.section_depths[0] = .4
        self.assertAlmostEqual(clone.section_depths[1], muscle.section_depths[1]*2)
        self.assertAlmostEqual(clone.inflation_secondary.section_depths[1], muscle.inflation_secondary.section_depths[1]*2)
        self.assertAlmostEqual(clone.inflation_secondary.inflation_max_value, .24)
        self.assertNotEqual(clone.inflation_secondary.section_depths[0], muscle.inflation_secondary.section_depths[0])

    def test_initial_envelope_from_surface(self):
        from anthroforge.app.use_cases.fiber_surface_create import create_native_muscle
        root, surface, muscle = fixture(); value = configuration(root, muscle); value['sides'] = 'both'
        other = create_native_muscle(root, bpy.context.scene, surface.id, 'Two Sides', value)
        self.assertEqual(configuration(root, other), value)
        self.assertGreater(len(mesh(root, other)), len(mesh(root, muscle)))

    def test_document_adoption_regeneration_and_mirror(self):
        from _helpers import root
        from test_authoring_profile_document import document, saved
        from test_authoring_mirrors import publish, check_pairs
        from test_authoring_v04 import call
        owner = root()
        with TemporaryDirectory() as folder:
            value = document(owner, folder); publish(self, owner, folder, value)
            muscle = owner.af_vcp_system.muscles[0]; muscle.envelope_sides = 'BOTH_SIDES'; muscle.inflation_secondary.section_depths = (0.,)*4
            before = mesh(owner, muscle).copy(); expected = configuration(owner, muscle)
            adopted = call(owner, folder, 'reconcile', value, mode='adopt'); self.assertEqual(adopted['status'], 'success', adopted)
            compiled = call(owner, folder, 'compile', value, 2); self.assertEqual(compiled['status'], 'success', compiled)
            result = call(owner, folder, 'publish', value, 2); self.assertTrue(result.get('published'), result)
            self.assertEqual(configuration(owner, muscle), expected); check_pairs(self, owner)
            np.testing.assert_allclose(mesh(owner, muscle), before, atol=1e-6, rtol=0)


def envelope_request(root, muscle, folder, identity='configure-envelope'):
    from test_authoring_native_profiles import request, call
    state = call(root, folder, request(root, 'inflation_inspect', identity+'-inspect', target=dict(muscle_id=muscle.id)))
    row = state['entities'][0]; config = row['configuration']; config['sides'] = 'both'
    return request(root, 'inflation_configure', identity, muscle_id=muscle.id, configuration=config,
        expected_scene_revision=state['scene_revision'], expected_base_revision=row['base_revision'],
        expected_configuration_revision=row['configuration_revision'])


class EnvelopeReceiptTests(BlenderTestCase):
    def test_replay_after_reopen_and_stale_secondary(self):
        from test_authoring_native_profiles import call
        owner, _, muscle = fixture(); name, identity = owner.name, muscle.id
        with TemporaryDirectory() as directory:
            payload = envelope_request(owner, muscle, directory)
            result = call(owner, directory, payload); self.assertTrue(result.get('published'), result)
            self.assertTrue(call(owner, directory, payload).get('replayed'))
            path = str(Path(directory)/'receipt.blend'); bpy.ops.wm.save_as_mainfile(filepath=path); bpy.ops.wm.open_mainfile(filepath=path)
            owner = bpy.data.objects[name]; muscle = next(m for m in owner.af_vcp_system.muscles if m.id == identity)
            self.assertTrue(call(owner, directory, payload).get('replayed'))
            muscle.inflation_secondary.section_roundness = 2
            result = call(owner, directory, payload)
            self.assertEqual(result['diagnostics'][0]['code'], 'STALE_PROFILE_RECEIPT')

    def test_journal_failure_rolls_back_side_and_geometry(self):
        from test_authoring_native_profiles import call, fail_response
        from anthroforge.core.authoring.storage import FileStore
        owner, _, muscle = fixture(); old = configuration(owner, muscle); before = mesh(owner, muscle).copy()
        with TemporaryDirectory() as directory:
            payload = envelope_request(owner, muscle, directory)
            with patch.object(FileStore, 'put', fail_response(FileStore.put)):
                result = call(owner, directory, payload)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(configuration(owner, muscle), old)
            np.testing.assert_array_equal(mesh(owner, muscle), before)
            self.assertNotIn('af_authoring_envelope_receipt', muscle)

    def test_gizmo_movement_changes_only_selected_side(self):
        from mathutils import Vector
        from anthroforge.core.visualization.muscle_sync import apply_muscle_control_update
        from anthroforge.core.vcp.muscle_inflation_state import inflation_control_world
        owner, _, muscle = fixture(False); muscle.envelope_sides = 'BOTH_SIDES'; muscle.envelope_edit_side = 'B'
        before = inflation_control_world(muscle)
        control = next(o for o in bpy.context.scene.objects if o.get('af_muscle_inflation_ctrl'))
        old_b = inflation_control_world(muscle.inflation_secondary)
        control.location += Vector((.1, .15, 0)); apply_muscle_control_update(register_muscle_sync(), owner, bpy.context.scene, control)
        self.assertEqual(inflation_control_world(muscle), before)
        self.assertNotEqual(inflation_control_world(muscle.inflation_secondary), old_b)


class EnvelopeBranchTests(BlenderTestCase):
    def test_branch_secondary_roundtrip_and_base_stability(self):
        from _branch_fixture import create_fixture
        from anthroforge.core.visualization.branch_control import branch_surface
        owner, muscle, connection, _ = synchronized_branch(); name, identity = owner.name, muscle.id
        base = mesh(owner, muscle, 'BASE').copy(); muscle.envelope_sides = 'BOTH_SIDES'
        connection.settings.inflation_secondary.inflation_max_value = .07
        expected = configuration(owner, muscle); before = mesh(owner, muscle).copy()
        with TemporaryDirectory() as directory:
            path = str(Path(directory)/'branch-envelope.blend'); bpy.ops.wm.save_as_mainfile(filepath=path); bpy.ops.wm.open_mainfile(filepath=path)
            owner = bpy.data.objects[name]; muscle = next(m for m in owner.af_vcp_system.muscles if m.id == identity)
            register_muscle_sync().sync_root_to_scene(owner, bpy.context.scene, {identity})
            self.assertEqual(configuration(owner, muscle), expected)
            np.testing.assert_allclose(mesh(owner, muscle), before, atol=1e-6, rtol=0)
            np.testing.assert_allclose(mesh(owner, muscle, 'BASE'), base, atol=1e-6, rtol=0)

    def test_branch_disable_reverse_and_unsupported_mode(self):
        from _branch_fixture import create_fixture
        owner, muscle, connection, _ = create_fixture(); muscle.envelope_sides = 'BOTH_SIDES'
        target, state = commands.inspect(owner, bpy.context.scene, muscle.id); config = state['configuration']
        _, _, first = commands.preview(target, config)
        config['reverse_sides'] = True; _, _, reverse = commands.preview(target, config)
        np.testing.assert_array_equal(first.results[0].faces, reverse.results[0].faces)
        np.testing.assert_array_equal(first.results[0].base_vertices, reverse.results[0].base_vertices)
        config['enabled'] = False; _, _, disabled = commands.preview(target, config)
        np.testing.assert_array_equal(disabled.results[0].inflated_vertices, disabled.results[0].base_vertices)
        self.assertEqual(len(disabled.results[0].inflated_faces), len(disabled.results[0].faces))
        config['parts'][1]['b'] = dict(config['parts'][0]['b'], mode='section_profile', parameters=dict(profile_version=1, depths=[dict(value=.1, unit='scene')]*4, peaks=[.5]*4, roundness=1, direction='smooth'))
        with self.assertRaisesRegex(ValueError, 'PROFILE_DOMAIN_UNSUPPORTED'): commands.preview(target, config)


def synchronized_branch():
    from _branch_fixture import create_fixture
    from anthroforge.core.visualization.fiber_surface_sync import register_fiber_surface_sync
    owner, muscle, connection, fibers = create_fixture()
    register_fiber_surface_sync().sync_root_to_scene(owner, bpy.context.scene)
    register_muscle_sync().sync_root_to_scene(owner, bpy.context.scene)
    return owner, muscle, connection, fibers


class EnvelopeDomainTests(BlenderTestCase):
    def test_domain_edit_preserves_envelope_and_matches_publication(self):
        from test_muscle_output_domain import plane
        from anthroforge.app.use_cases import muscle_domain
        owner, _, muscle = fixture(); muscle.envelope_sides = 'BOTH_SIDES'
        config = configuration(owner, muscle); target, _ = commands.inspect(owner, bpy.context.scene, muscle.id)
        request, batch = muscle_domain.preview(target, plane())
        self.assertIsNotNone(batch.results[0].side_b)
        muscle_domain.configure(owner, bpy.context.scene, muscle.id, plane())
        self.assertEqual(configuration(owner, muscle), config)
        np.testing.assert_array_equal(mesh(owner, muscle), batch.results[0].inflated_vertices.astype(np.float32))

    def test_one_side_profile_api_retains_master_disable(self):
        from anthroforge.app.use_cases import muscle_profile
        owner, _, muscle = fixture(); muscle.envelope_sides = 'BOTH_SIDES'; muscle.envelope_enabled = False
        muscle.envelope_sides = 'ONE_SIDE'; target, state = muscle_profile.inspect(owner, bpy.context.scene, muscle.id)
        _, _, batch = muscle_profile.preview(target, state['configuration'])
        np.testing.assert_array_equal(batch.results[0].base_vertices, batch.results[0].inflated_vertices)
