"""Current intrinsic output, real publication, persistence and authoring parity."""
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase
from _stacking_fixture import fixture
from test_muscle_pairs import finish
from test_muscle_section_profile import mesh
from anthroforge.core.muscle_pairs import runtime, configuration
from anthroforge.core.muscle_pairs.capture import DomainCaptureAdapter


def refresh(root):
    runtime.refresh(bpy.context.scene, root, True); finish()
    return runtime.inspect(bpy.context.scene, root)


def call(root, journal, op, **params):
    from anthroforge.app.authoring.api import execute
    return execute(dict(dsl='anthroforge.authoring.protocol', version='0.4.0', message_type='request', request_id=str(uuid4()),
        op='muscles.'+op, params=dict(scene_id=root.name, **params)), root, bpy.context.scene, journal)


class StackingBlenderTests(BlenderTestCase):
    def test_actual_stacking_and_no_accumulation(self):
        root, under, cover = fixture(); own = mesh(root, cover).copy(); bases = mesh(root, cover, 'BASE').copy()
        state = refresh(root); self.assertEqual(state['stacking']['status'], 'complete', state)
        result = mesh(root, cover).copy(); self.assertGreater(np.max(np.linalg.norm(result-own, axis=1)), .01, state)
        for _ in range(3): refresh(root); np.testing.assert_array_equal(mesh(root, cover), result)
        np.testing.assert_array_equal(mesh(root, cover, 'BASE'), bases)
        domains, issues, _ = DomainCaptureAdapter().capture((bpy.context.scene, root), configuration.settings(root))
        self.assertFalse(issues); captured = next(d for d in domains if d.key.muscle == cover.id)
        np.testing.assert_allclose(captured.own, own, atol=1e-6)
        root.af_pair_settings.stacking = False; finish(); np.testing.assert_array_equal(mesh(root, cover), own)

    def test_preview_does_not_publish_and_configuration_is_guarded(self):
        root, _, cover = fixture(); state = refresh(root); before = mesh(root, cover).copy()
        with TemporaryDirectory() as journal:
            result = call(root, journal, 'stacking_preview', configuration=dict(stacking=False))
            self.assertEqual(result['status'], 'success', result); np.testing.assert_array_equal(mesh(root, cover), before)
            report = call(root, journal, 'stacking_inspect'); current = report['entities'][0]['detection']
            self.assertEqual(current['result_revision'], state['result_revision'])
            result = call(root, journal, 'stacking_configure', configuration=dict(stacking=False),
                expected_scene_revision=report['scene_revision'], expected_configuration_revision=current['configuration_revision'])
            self.assertEqual(result['status'], 'success', result); finish()
            self.assertFalse(configuration.read(root)['stacking'])

    def test_reopen_rebuild_and_visible_fibers(self):
        root, _, cover = fixture(); state = refresh(root); before = mesh(root, cover).copy(); name, mid = root.name, cover.id
        self.assertEqual(state['stacking']['status'], 'complete', state)
        with TemporaryDirectory() as folder:
            path = str(Path(folder)/'stacked.blend'); bpy.ops.wm.save_as_mainfile(filepath=path); bpy.ops.wm.open_mainfile(filepath=path)
            root = bpy.data.objects[name]; cover = next(m for m in root.af_vcp_system.muscles if m.id == mid); refresh(root)
            np.testing.assert_allclose(mesh(root, cover), before, atol=2e-6)
            self.assertTrue(configuration.read(root)['stacking'])
            fibers = [o for o in bpy.context.scene.objects if o.get('af_fiber_proxy')]
            self.assertTrue(fibers); self.assertTrue(all(not o.hide_get() and o.display_type != 'WIRE' for o in fibers))

    def test_exclusion_restores_own(self):
        root, _, cover = fixture(); own = mesh(root, cover).copy(); state = refresh(root)
        pair = next(p for p in state['pairs'] if p['order']['status'] == 'supported')
        keys = [[pair[k][name] for name in ('muscle', 'instance', 'side')] for k in ('first', 'second')]
        with configuration.transaction(root, dict(exclusions=[keys])): pass
        state = refresh(root); np.testing.assert_array_equal(mesh(root, cover), own)
        # Exclusion is now policy; the raw geometric evidence remains inspectable.
        self.assertEqual(state['pairs'][pair['index']]['policy']['status'], 'excluded')
        self.assertEqual(state['pairs'][pair['index']]['order']['status'], 'supported')

    def test_publication_failure_restores_current_own(self):
        root, _, cover = fixture(); own = mesh(root, cover).copy()
        with patch('anthroforge.core.muscle_stacking.downstream.refresh', side_effect=ValueError('consumer failed')):
            state = refresh(root)
        self.assertEqual(state['stacking']['publication'], 'failed')
        np.testing.assert_array_equal(mesh(root, cover), own)
        self.assertEqual(refresh(root)['stacking']['publication'], 'published')

    def test_stacking_journal_failure_rolls_back(self):
        from anthroforge.core.authoring.storage import FileStore
        from test_muscle_pairs import response_failure
        root, _, cover = fixture(); refresh(root); before = mesh(root, cover).copy(); config = configuration.inspect(root)
        with TemporaryDirectory() as journal:
            report = call(root, journal, 'stacking_inspect')
            with patch.object(FileStore, 'put', response_failure(FileStore.put)):
                result = call(root, journal, 'stacking_configure', configuration=dict(stacking=False),
                    expected_scene_revision=report['scene_revision'], expected_configuration_revision=config['configuration_revision'])
            self.assertNotEqual(result['status'], 'success'); self.assertEqual(configuration.inspect(root), config)
            np.testing.assert_array_equal(mesh(root, cover), before)

    def test_cropped_cover_has_mobile_generated_border(self):
        from anthroforge.app.use_cases import muscle_domain
        from test_muscle_output_domain import plane
        root, _, cover = fixture(); muscle_domain.configure(root, bpy.context.scene, cover.id, plane(0, .9))
        own = mesh(root, cover).copy(); state = refresh(root)
        self.assertEqual(state['stacking']['status'], 'complete', state)
        after = mesh(root, cover); cut = np.isclose(after[:, 0], .9)
        self.assertGreater(np.max(np.linalg.norm(after[cut]-own[cut], axis=1)), .01)

    def test_real_mirror_publication_and_intrinsic_capture(self):
        from mathutils import Matrix
        from anthroforge.core.muscle_pairs.capture import geometry
        root, _, cover = fixture(); source = next(o for o in bpy.context.scene.objects if o.get('af_muscle_id') == cover.id and o.get('af_muscle_surface') == 'INFL')
        for obj in tuple(bpy.context.scene.objects):
            if not obj.get('af_muscle_proxy') or obj.get('af_muscle_surface') != 'INFL': continue
            mirror = obj.copy(); mirror.data = obj.data.copy(); bpy.context.scene.collection.objects.link(mirror)
            mirror['af_muscle_mirror_proxy'] = True; mirror['af_source_muscle_id'] = obj['af_muscle_id']
            mirror.matrix_world = Matrix.Translation((6, 0, 0)) @ Matrix.Diagonal((-1., 1., 1., 1.))
        state = refresh(root); self.assertEqual(state['stacking']['status'], 'complete', state)
        mirror = next(o for o in bpy.context.scene.objects if o.get('af_muscle_mirror_proxy') and o.get('af_source_muscle_id') == cover.id)
        np.testing.assert_allclose(geometry(mirror), geometry(source)*(-1, 1, 1)+(6, 0, 0), atol=2e-6)
        self.assertFalse(DomainCaptureAdapter().capture((bpy.context.scene, root), configuration.settings(root))[1])

    def test_order_evidence_export_and_stale_revision(self):
        root, _, _ = fixture(); state = refresh(root)
        index = next(p['index'] for p in state['pairs'] if p['order']['status'] == 'supported')
        with TemporaryDirectory() as journal:
            result = call(root, journal, 'pairs_order_footprint', pair_index=index, expected_result_revision=state['result_revision'])
            self.assertEqual(result['status'], 'success', result); self.assertTrue(Path(result['assets'][0]['path']).exists())
            runtime.refresh(bpy.context.scene, root, True)
            result = call(root, journal, 'pairs_order_footprint', pair_index=index, expected_result_revision=state['result_revision'])
            self.assertNotEqual(result['status'], 'success')
