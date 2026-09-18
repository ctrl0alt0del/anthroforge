"""Document profile publication, native parity, mirror and explicit adoption."""
from tempfile import TemporaryDirectory
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase, root
from test_authoring_v04 import call
from test_authoring_mirrors import mirrored_document, publish, check_pairs
from test_muscle_section_profile import mesh
from test_authoring_native_profiles import configure
from anthroforge.app.use_cases import muscle_profile as commands
from anthroforge.core.authoring.profile_config import wire
from anthroforge.core.authoring.storage import FileStore
from anthroforge.core.vcp.muscle_section_profile import reset_profile
from anthroforge.core.vcp.fiber_solver import FiberSolver
from anthroforge.core.visualization import muscle_numeric_runtime


def document(owner, folder):
    value = mirrored_document(owner, folder)
    for shape in value['shape_presets'].values():
        native = shape['native']
        metadata = {key: native[key] for key in ('applies_to', 'calibration', 'shape_checks', 'evidence')}
        shape['native'] = dict(metadata, **wire(reset_profile(.2)))
        shape['native']['shape_checks'] = [dict(metric='normal_height', statistic='max', s=.5, u_range=[0, 1],
            minimum=dict(value=0, unit='scene'), maximum=dict(value=10, unit='scene'))]
        shape.pop('intent', None)
    return value


def saved(owner, folder, value):
    return FileStore(folder).get('v04_drafts', [owner['af_authoring_id'], value['document_id']])


def failed_configuration(owner, folder, muscle):
    from test_authoring_native_profiles import inspect, request, call, fail_response
    _, guards = inspect(owner, folder, dict(muscle_id=muscle.id))
    payload = request(owner, 'profile_configure', 'injected-failure', muscle_id=muscle.id, configuration=wire(reset_profile(.3)), **guards)
    with patch.object(FileStore, 'put', fail_response(FileStore.put)):
        return call(owner, folder, payload)


class DocumentProfileTests(BlenderTestCase):
    def test_untouched_profile_preserves_legacy_ownership_vocabulary(self):
        from test_muscle_section_profile import fixture
        from anthroforge.adapters.authoring.records import record
        from anthroforge.core.vcp.muscle_section_profile import PROFILE_FIELDS
        _, _, muscle = fixture(False)
        self.assertTrue(set(PROFILE_FIELDS).isdisjoint(record(muscle)['values']))
        muscle.section_profile_version = 77
        self.assertEqual(record(muscle)['values']['section_profile_version'], 77)
        muscle.section_profile_version = 0
        muscle.section_depths[0] = .3
        self.assertAlmostEqual(record(muscle)['values']['section_depths'][0], .3)

    def test_failed_native_edit_restores_shared_mirror_data_and_receipt(self):
        owner = root()
        with TemporaryDirectory() as folder:
            value = document(owner, folder); publish(self, owner, folder, value)
            muscle = owner.af_vcp_system.muscles[0]
            before, journal = mesh(owner, muscle).copy(), owner.get('af_authoring_journal')
            reply = failed_configuration(owner, folder, muscle)
            self.assertEqual(reply['status'], 'failed')
            np.testing.assert_array_equal(mesh(owner, muscle), before)
            self.assertEqual(owner.get('af_authoring_journal'), journal)
            self.assertNotIn('af_authoring_profile_receipt', muscle)
            check_pairs(self, owner)

    def test_document_manual_and_native_geometry_share_chart_and_mirror(self):
        owner = root()
        with TemporaryDirectory() as folder:
            value = document(owner, folder); publish(self, owner, folder, value)
            muscle = owner.af_vcp_system.muscles[0]
            output = next(iter(saved(owner, folder, value)['compiled']['outputs'].values()))
            np.testing.assert_allclose(mesh(owner, muscle), output['inflated'], atol=1e-6, rtol=0)
            target, state = commands.inspect(owner, bpy.context.scene, muscle.id)
            _, _, batch = commands.preview(target, state['configuration'])
            np.testing.assert_allclose(mesh(owner, muscle), batch.results[0].inflated_vertices, atol=1e-6, rtol=0)
            with patch.object(FiberSolver, 'solve_points', side_effect=AssertionError('profile-induced solve')):
                bpy.ops.af.muscle_profile_scale(muscle_id=muscle.id, factor=2)
            check_pairs(self, owner)
            self.assertEqual(len(owner.af_vcp_system.fibers), len(output['fibers']))

    def test_native_edit_retains_document_fingerprint_and_complete_adoption(self):
        owner = root()
        with TemporaryDirectory() as folder:
            value = document(owner, folder); publish(self, owner, folder, value)
            baseline = saved(owner, folder, value)['published']
            muscle = owner.af_vcp_system.muscles[0]
            reply, _ = configure(owner, folder, muscle.id)
            self.assertTrue(reply['published'], reply)
            self.assertEqual(saved(owner, folder, value)['published'], baseline)
            expected = tuple(muscle.section_depths)
            adopted = call(owner, folder, 'reconcile', value, mode='adopt')
            self.assertEqual(adopted['status'], 'success', adopted)
            self.assertEqual(call(owner, folder, 'compile', value, 2)['status'], 'success')
            self.assertTrue(call(owner, folder, 'publish', value, 2)['published'])
            self.assertEqual(tuple(owner.af_vcp_system.muscles[0].section_depths), expected)

    def test_profile_callback_publishes_only_target_without_solver(self):
        from test_muscle_section_profile import fixture
        from anthroforge.app.use_cases.fiber_surface_create import create_native_muscle
        owner, source, muscle = fixture()
        other = create_native_muscle(owner, bpy.context.scene, source.id, 'Other', wire(reset_profile(.1)))
        before = mesh(owner, other).copy(); counts = [(f.id, len(f.mid_touches)) for f in owner.af_vcp_system.fibers]
        with patch.object(FiberSolver, 'solve_points', side_effect=AssertionError('profile-induced solve')):
            with patch.object(muscle_numeric_runtime, '_publish_valid', wraps=muscle_numeric_runtime._publish_valid) as publish_result:
                muscle.section_depths[0] *= 2
        self.assertEqual([args.args[6].muscle_id for args in publish_result.call_args_list], [muscle.id])
        np.testing.assert_array_equal(mesh(owner, other), before)
        self.assertEqual([(f.id, len(f.mid_touches)) for f in owner.af_vcp_system.fibers], counts)
