"""Production height smoothing: geometry, side ownership, authoring and persistence."""
from dataclasses import replace, asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
import bpy
import numpy as np
from _helpers import BlenderTestCase
from test_muscle_numeric_backends import _spec, _grid
from test_muscle_section_profile import fixture, mesh
from anthroforge.core.vcp.height_smoothing import HeightSmoothing, normalize
from anthroforge.core.vcp.height_smoothing_native import smooth
from anthroforge.core.vcp.muscle_numeric import execute_muscle_batch, make_muscle_request
from anthroforge.core.vcp.branched_surface import quads
from anthroforge.core.authoring.envelope_config import configuration
from anthroforge.app.use_cases import muscle_envelope as commands


def cap(count=25):
    y, x = np.meshgrid(np.linspace(0, 1, count), np.linspace(0, 1, count), indexing='ij')
    base = np.stack((x, y, x*0), axis=-1)
    h = .2*np.sin(np.pi*x)*np.sin(np.pi*y)
    noise = .02*np.sin(14*np.pi*x)*np.sin(14*np.pi*y)
    own = base.copy(); own[:, :, 2] = h+noise
    own[[0, -1], :, 2] = 0; own[:, [0, -1], 2] = 0
    faces = quads(base.shape)
    return base.reshape(-1, 3), own.reshape(-1, 3), faces, h.ravel()


def denoise(base, own, faces, setting=HeightSmoothing('HEIGHT', .04, .8, .05)):
    return smooth(base, own, faces, np.zeros(len(faces), dtype=int), 0, setting)


class HeightNativeTests(unittest.TestCase):
    def test_collapsed_attachment_tip_is_retained(self):
        base, own, faces, _ = cap(17)
        base[:17] = base[0]; own[:17] = base[0]
        result, report = denoise(base, own, faces)
        np.testing.assert_array_equal(result[:17], own[:17])
        self.assertEqual(report['skipped_triangles'], 16)

    def test_known_shape_noise_and_exact_rim(self):
        base, own, faces, truth = cap()
        result, report = denoise(base, own, faces)
        self.assertLess(np.linalg.norm(result[:, 2]-truth), np.linalg.norm(own[:, 2]-truth)*.5)
        np.testing.assert_array_equal(result[own[:, 2] == 0], own[own[:, 2] == 0])
        self.assertLessEqual(np.max(np.abs(result-own)), .05+1e-8)
        self.assertLess(report['violation'], 2e-7)
        self.assertLess(report['stationarity'], 2e-7)
        self.assertEqual(report['status'], 0)

    def test_scale_covariance_and_rigid_rotation(self):
        base, own, faces, _ = cap(17); expected, _ = denoise(base, own, faces)
        scaled, _ = denoise(base*10, own*10, faces, HeightSmoothing('HEIGHT', .4, .8, .5))
        np.testing.assert_allclose(scaled/10, expected, atol=1e-7)
        rotated, _ = denoise(base[:, [2, 0, 1]], own[:, [2, 0, 1]], faces)
        np.testing.assert_allclose(rotated, expected[:, [2, 0, 1]], atol=1e-8)

    def test_zero_height_crease_and_partial_setting(self):
        base, own, faces, _ = cap(17); own[8*17:9*17, 2] = 0
        result, _ = denoise(base, own, faces)
        np.testing.assert_array_equal(result[8*17:9*17], own[8*17:9*17])
        limited, report = denoise(base, own, faces, HeightSmoothing('HEIGHT', .5, 1, .001))
        self.assertLessEqual(report['max_change'], .001+1e-8)
        self.assertTrue(np.isfinite(limited).all())

    def test_invalid_configuration_and_geometry(self):
        for value in (dict(mode='X', radius=.1, strength=1, max_change=.1),
                      dict(mode='HEIGHT', radius=float('nan'), strength=1, max_change=.1)):
            with self.assertRaises(ValueError): normalize(value)
        base, own, faces, _ = cap(9)
        with self.assertRaisesRegex(ValueError, 'Face index'): denoise(base, own, faces+10000)
        with self.assertRaisesRegex(ValueError, 'Nonfinite'): denoise(base*np.nan, own, faces)


def request(mode='DISTRIBUTED', **changes):
    return make_muscle_request('smoothing', _grid(7, 17), _spec(mode, target_count=17, **changes))


def evaluated(value):
    result = execute_muscle_batch((value,)).results[0]
    if result.error: raise AssertionError(result.error)
    return result


class HeightPipelineTests(unittest.TestCase):
    def test_free_samples_and_disabled_inflation(self):
        value = request(preserve_samples=True, smoothing=HeightSmoothing('HEIGHT'))
        current = evaluated(value)
        self.assertIn('height_smoothing', current.diagnostics)
        off = replace(value, spec=replace(value.spec, inflation_enabled=False))
        with patch('anthroforge.core.vcp.height_smoothing_native.library', side_effect=AssertionError('loaded')):
            actual = evaluated(off)
        np.testing.assert_array_equal(actual.base_vertices, actual.inflated_vertices)

    def test_changed_input_has_no_stale_cached_result(self):
        value = request(smoothing=HeightSmoothing('HEIGHT'))
        old = evaluated(value)
        updated = replace(value, points=value.points*np.array([1., 1., 1.5]))
        new = evaluated(updated)
        self.assertGreater(np.max(np.abs(new.inflated_vertices-old.inflated_vertices)), .001)
        np.testing.assert_array_equal(evaluated(value).inflated_vertices, old.inflated_vertices)

    def test_off_bypasses_native_library_and_is_identical(self):
        value = request(); expected = evaluated(value)
        with patch('anthroforge.core.vcp.height_smoothing_native.library', side_effect=AssertionError('loaded')):
            actual = evaluated(replace(value, spec=replace(value.spec, smoothing=HeightSmoothing())))
        np.testing.assert_array_equal(actual.inflated_vertices, expected.inflated_vertices)

    def test_all_modes_keep_base_and_boundaries(self):
        from anthroforge.core.vcp.muscle_section_profile import reset_profile
        for mode in ('DISTRIBUTED', 'CTRL_POINT', 'SECTION_PROFILE'):
            value = request(mode, section_profile=reset_profile(.2))
            expected = evaluated(value)
            result = evaluated(replace(value, spec=replace(value.spec, smoothing=HeightSmoothing('HEIGHT'))))
            np.testing.assert_array_equal(result.base_vertices, expected.base_vertices)
            self.assertLessEqual(np.max(np.linalg.norm(result.inflated_vertices-expected.inflated_vertices, axis=1)), .050001)
            self.assertIn('height_smoothing', result.diagnostics)

    def test_crop_interpolates_smoothed_full_domain(self):
        from anthroforge.core.vcp.muscle_output_domain import apply_result
        value = request(smoothing=HeightSmoothing('HEIGHT'))
        cropped = replace(value, output_domain=dict(normal=(1., 0., 0.), offset=1., keep_positive=True))
        actual = evaluated(cropped); expected = apply_result(cropped, evaluated(value))
        np.testing.assert_allclose(actual.inflated_vertices, expected.inflated_vertices, atol=1e-12)

    def test_envelope_a_and_b_are_independent(self):
        from anthroforge.core.vcp.muscle_envelope import MuscleEnvelopeSpec
        value = request(); value = replace(value, envelope=MuscleEnvelopeSpec((value.spec,)))
        old = evaluated(value)
        value = replace(value, spec=replace(value.spec, smoothing=HeightSmoothing('HEIGHT')))
        new = evaluated(value)
        np.testing.assert_array_equal(new.side_b, old.side_b)
        self.assertGreater(np.max(np.abs(new.side_a-old.side_a)), 1e-6)
        np.testing.assert_array_equal(new.base_vertices, old.base_vertices)

    def test_branched_interface_is_shared_and_fixed(self):
        from test_branched_inflation import fixture as branch_fixture
        from anthroforge.core.vcp.branched_numeric import BranchedMuscleRequest
        assembly = branch_fixture(); spec = _spec('DISTRIBUTED')
        value = BranchedMuscleRequest('branch', assembly, (spec, spec))
        old = evaluated(value)
        new = evaluated(replace(value, part_specs=(replace(spec, smoothing=HeightSmoothing('HEIGHT')),)*2))
        seam = (len(assembly.main)-1)*assembly.main.shape[1]+assembly.branches[0].seam
        np.testing.assert_array_equal(new.inflated_vertices[seam], old.inflated_vertices[seam])
        self.assertEqual(len(new.diagnostics['height_smoothing']['a']), 2)


class HeightBlenderTests(BlenderTestCase):
    def test_legacy_profile_receipt_detects_smoothing_change(self):
        from test_authoring_native_profiles import configure, call
        root, _, muscle = fixture()
        with TemporaryDirectory() as directory:
            result, payload = configure(root, directory, muscle.id)
            self.assertTrue(result.get('published'), result)
            muscle.inflation_smoothing_mode = 'HEIGHT'
            result = call(root, directory, payload)
            self.assertEqual(result['diagnostics'][0]['code'], 'STALE_PROFILE_RECEIPT')

    def test_authoring_journal_replay_and_changed_settings(self):
        from test_muscle_envelope import envelope_request
        from test_authoring_native_profiles import call
        root, _, muscle = fixture()
        with TemporaryDirectory() as directory:
            payload = envelope_request(root, muscle, directory)
            payload['params']['configuration']['parts'][0]['b']['smoothing'] = asdict(HeightSmoothing('HEIGHT'))
            result = call(root, directory, payload); self.assertTrue(result.get('published'), result)
            self.assertTrue(call(root, directory, payload).get('replayed'))
            muscle.inflation_secondary.inflation_smoothing_radius = .3
            result = call(root, directory, payload)
            self.assertEqual(result['diagnostics'][0]['code'], 'STALE_PROFILE_RECEIPT')

    def test_document_adoption_regeneration_and_mirror(self):
        from _helpers import root
        from test_authoring_profile_document import document
        from test_authoring_mirrors import publish, check_pairs
        from test_authoring_v04 import call
        owner = root()
        with TemporaryDirectory() as directory:
            value = document(owner, directory); publish(self, owner, directory, value)
            muscle = owner.af_vcp_system.muscles[0]; muscle.inflation_smoothing_mode = 'HEIGHT'
            before = mesh(owner, muscle).copy(); expected = configuration(owner, muscle)
            self.assertEqual(call(owner, directory, 'reconcile', value, mode='adopt')['status'], 'success')
            self.assertEqual(call(owner, directory, 'compile', value, 2)['status'], 'success')
            self.assertTrue(call(owner, directory, 'publish', value, 2).get('published'))
            self.assertEqual(configuration(owner, muscle), expected); check_pairs(self, owner)
            np.testing.assert_allclose(mesh(owner, muscle), before, atol=1e-6, rtol=0)

    def test_ui_changes_rebuild_and_off_restores(self):
        root, _, muscle = fixture(); old = mesh(root, muscle).copy(); base = mesh(root, muscle, 'BASE').copy()
        muscle.inflation_smoothing_mode = 'HEIGHT'
        self.assertGreater(len(mesh(root, muscle)), 0, muscle.get('_af_rt_section_profile_error'))
        self.assertGreater(np.max(np.abs(mesh(root, muscle)-old)), 1e-6)
        np.testing.assert_array_equal(mesh(root, muscle, 'BASE'), base)
        muscle.inflation_smoothing_mode = 'OFF'
        np.testing.assert_array_equal(mesh(root, muscle), old)

    def test_authoring_preview_configure_and_rollback(self):
        root, _, muscle = fixture(); before = configuration(root, muscle); old = mesh(root, muscle).copy()
        config = configuration(root, muscle); config['parts'][0]['a']['smoothing'] = asdict(HeightSmoothing('HEIGHT'))
        target, _ = commands.inspect(root, bpy.context.scene, muscle.id)
        _, _, batch = commands.preview(target, config)
        np.testing.assert_array_equal(mesh(root, muscle), old)
        with patch.object(commands, 'publish', side_effect=ValueError('injected')):
            with self.assertRaises(ValueError): commands.configure(root, bpy.context.scene, muscle.id, config)
        self.assertEqual(configuration(root, muscle), before)
        commands.configure(root, bpy.context.scene, muscle.id, config)
        np.testing.assert_allclose(mesh(root, muscle), batch.results[0].inflated_vertices, atol=1e-6)

    def test_persistence_secondary_and_scaled_import(self):
        root, _, muscle = fixture(); muscle.envelope_sides = 'BOTH_SIDES'
        muscle.inflation_secondary.inflation_smoothing_mode = 'HEIGHT'
        old = mesh(root, muscle).copy(); expected = configuration(root, muscle)
        name, identity = root.name, muscle.id
        with TemporaryDirectory() as directory:
            path = str(Path(directory)/'smoothing.blend'); bpy.ops.wm.save_as_mainfile(filepath=path)
            bpy.ops.wm.open_mainfile(filepath=path)
            root = bpy.data.objects[name]; muscle = next(m for m in root.af_vcp_system.muscles if m.id == identity)
            from anthroforge.core.visualization.muscle_profile_publish import refresh
            refresh(root, bpy.context.scene, identity)
            self.assertEqual(configuration(root, muscle), expected)
            np.testing.assert_array_equal(mesh(root, muscle), old)
        self._scaled(root, muscle)

    def _scaled(self, root, muscle):
        from anthroforge.core.importing.rna import scalar_dict, apply_scalar_dict
        from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
        with suppress_vcp_prop_updates():
            other = root.af_vcp_system.muscles.add(); apply_scalar_dict(other, scalar_dict(muscle), geometry_scale=2)
        self.assertAlmostEqual(other.inflation_secondary.inflation_smoothing_radius, .4)
        self.assertAlmostEqual(other.inflation_secondary.inflation_smoothing_max_change, .1)
