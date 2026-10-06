"""Real Blender capture, shared adapters, no-solver evaluation and persistence."""
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from uuid import uuid4
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase
from test_muscle_section_profile import fixture, mesh
from anthroforge.core.muscle_pairs import runtime, configuration
from anthroforge.core.muscle_pairs.capture import DomainCaptureAdapter
from anthroforge.core.muscle_pairs.model import DetectionSettings


def finish():
    deadline = monotonic()+20
    while runtime.COORDINATOR.tick() and monotonic() < deadline: sleep(.01)
    if runtime.COORDINATOR.active: raise AssertionError('pair job timeout')


def call(root, journal, op, **params):
    from anthroforge.app.authoring.api import execute
    return execute(dict(dsl='anthroforge.authoring.protocol', version='0.4.0', message_type='request', request_id=str(uuid4()),
        op='muscles.pairs_'+op, params=dict(scene_id=root.name, **params)), root, bpy.context.scene, journal)


def response_failure(original):
    def fail(store, category, key, value):
        if category == 'v04_requests': raise ValueError('disk failure')
        return original(store, category, key, value)
    return fail


class PairBlenderTests(BlenderTestCase):
    def test_display_helper_transform_does_not_invalidate(self):
        root, _, _ = fixture(); helper = bpy.data.objects.new('display helper', None)
        helper['af_root_name'] = root.name; bpy.context.scene.collection.objects.link(helper)
        runtime.refresh(bpy.context.scene, root, True); finish(); revision = runtime.inspect(bpy.context.scene, root)['result_revision']
        helper.location.x = 5; bpy.context.view_layer.update()
        self.assertEqual(runtime.inspect(bpy.context.scene, root)['result_revision'], revision)

    def test_actual_undo_redo_restore_configuration_and_rescan(self):
        root, _, _ = fixture(); name = root.name; runtime.refresh(bpy.context.scene, root, True); finish()
        bpy.ops.ed.undo_push(message='Pair defaults'); epoch = runtime.COORDINATOR.epoch
        root.af_pair_settings.search = .123; bpy.ops.ed.undo_push(message='Pair settings')
        bpy.ops.ed.undo(); root = bpy.data.objects[name]; sleep(.16); finish()
        self.assertGreater(runtime.COORDINATOR.epoch, epoch)
        self.assertAlmostEqual(configuration.read(root)['search_distance'], .05)
        self.assertEqual(runtime.inspect(bpy.context.scene, root)['status'], 'complete')
        bpy.ops.ed.redo(); root = bpy.data.objects[name]; sleep(.16); finish()
        self.assertAlmostEqual(configuration.read(root)['search_distance'], .123)
        self.assertEqual(runtime.inspect(bpy.context.scene, root)['status'], 'complete')

    def test_mirrored_identity_positions_directions_and_winding(self):
        from mathutils import Matrix
        from types import SimpleNamespace
        from anthroforge.core.muscle_pairs.capture import mirror_domains
        root, _, _ = fixture(); domains, issues, _ = DomainCaptureAdapter().capture((bpy.context.scene, root), DetectionSettings())
        source = SimpleNamespace(matrix_world=Matrix.Identity(4)); mirror = SimpleNamespace(matrix_world=Matrix.Diagonal((-1., 1., 1., 1.)))
        reflected = mirror_domains(domains, source, mirror)[0]; original = domains[0]
        self.assertFalse(issues); self.assertEqual(reflected.key.instance, 'mirror')
        np.testing.assert_allclose(reflected.own, original.own * (-1, 1, 1))
        np.testing.assert_allclose(reflected.direction, original.direction * (-1, 1, 1))
        np.testing.assert_array_equal(reflected.faces, original.faces[:, ::-1])
        np.testing.assert_array_equal(reflected.sources, original.sources)

    def test_undo_redo_and_shutdown_handlers_invalidate_epoch(self):
        root, _, _ = fixture(); runtime.refresh(bpy.context.scene, root, True); finish()
        for before, after in ((bpy.app.handlers.undo_pre, bpy.app.handlers.undo_post), (bpy.app.handlers.redo_pre, bpy.app.handlers.redo_post)):
            epoch = runtime.COORDINATOR.epoch
            self.assertIn(runtime.before_change, before); self.assertIn(runtime.after_change, after)
            runtime.before_change(None); runtime.after_change(None); sleep(.16); finish()
            self.assertGreater(runtime.COORDINATOR.epoch, epoch)
            self.assertEqual(runtime.inspect(bpy.context.scene, root)['status'], 'complete')
        runtime.unregister(); self.assertFalse(runtime.COORDINATOR.entries)
        self.assertFalse(bpy.app.timers.is_registered(runtime.tick)); runtime.register()

    def test_footprint_export_and_stale_revision_rejection(self):
        from anthroforge.app.use_cases.fiber_surface_create import create_native_muscle
        root, surface, muscle = fixture(); create_native_muscle(root, bpy.context.scene, surface.id, 'Second')
        runtime.refresh(bpy.context.scene, root, True); finish()
        state = runtime.inspect(bpy.context.scene, root); index = next(p['index'] for p in state['pairs'] if p['fragments'])
        with TemporaryDirectory() as journal:
            report = call(root, journal, 'footprint', pair_index=index, expected_result_revision=state['result_revision'])
            self.assertEqual(report['status'], 'success', report); self.assertTrue(Path(report['assets'][0]['path']).exists())
            runtime.refresh(bpy.context.scene, root, True)
            bad = call(root, journal, 'footprint', pair_index=index, expected_result_revision=state['result_revision'])
            self.assertNotEqual(bad['status'], 'success')

    def test_configuration_journal_failure_rolls_back(self):
        from anthroforge.core.authoring.storage import FileStore
        root, _, muscle = fixture(); before = configuration.inspect(root)
        with TemporaryDirectory() as journal:
            report = call(root, journal, 'inspect'); guards = dict(expected_scene_revision=report['scene_revision'], expected_configuration_revision=before['configuration_revision'])
            with patch.object(FileStore, 'put', response_failure(FileStore.put)):
                result = call(root, journal, 'configure', configuration=dict(search_distance=.7, groups={muscle.id: 'changed'}), **guards)
            self.assertNotEqual(result['status'], 'success')
            self.assertEqual(configuration.inspect(root), before)

    def test_publication_and_deletion_refresh_automatically(self):
        root, _, muscle = fixture(); sleep(.16); finish(); first = runtime.inspect(bpy.context.scene, root)['result_revision']
        muscle.section_roundness = 1.8; sleep(.16); finish()
        self.assertNotEqual(runtime.inspect(bpy.context.scene, root)['result_revision'], first)
        root.af_vcp_system.muscles.remove(0); runtime.reconcile(bpy.context.scene); sleep(.16); finish()
        self.assertEqual(runtime.inspect(bpy.context.scene, root)['pairs'], ())

    def test_readonly_capture_matches_published_surface(self):
        root, _, muscle = fixture(); before = mesh(root, muscle).copy()
        from anthroforge.core.visualization.muscle_sync import register_muscle_sync
        with patch.object(register_muscle_sync(), '_collect_points_with_fallback', side_effect=AssertionError('rerouted')):
            domains, issues, _ = DomainCaptureAdapter().capture((bpy.context.scene, root), DetectionSettings())
        self.assertFalse(issues, issues); self.assertEqual(len(domains), 1)
        np.testing.assert_allclose(domains[0].own, before, atol=1e-6)
        np.testing.assert_array_equal(mesh(root, muscle), before)

    def test_authoring_and_runtime_same_revision(self):
        root, _, _ = fixture()
        with TemporaryDirectory() as journal:
            result = call(root, journal, 'refresh'); self.assertEqual(result['status'], 'success', result)
            finish(); report = call(root, journal, 'inspect')
            self.assertEqual(report['status'], 'success', report)
            state = report['entities'][0]['detection']
            self.assertEqual(state['result_revision'], runtime.inspect(bpy.context.scene, root)['result_revision'])
            self.assertEqual(state['status'], 'complete', state)

    def test_invalid_muscle_produces_incomplete(self):
        root, _, muscle = fixture()
        obj = next(o for o in bpy.context.scene.objects if o.get('af_muscle_id') == muscle.id and o.get('af_muscle_surface') == 'INFL')
        obj['af_muscle_output_state'] = 'STALE'
        runtime.refresh(bpy.context.scene, root, True); finish()
        self.assertEqual(runtime.inspect(bpy.context.scene, root)['status'], 'incomplete')

    def test_configuration_revision_guards_and_grouping(self):
        root, _, muscle = fixture()
        with TemporaryDirectory() as journal:
            report = call(root, journal, 'inspect'); state = report['entities'][0]['detection']
            guards = dict(expected_scene_revision=report['scene_revision'], expected_configuration_revision=state['configuration_revision'])
            result = call(root, journal, 'configure', configuration=dict(automatic=False, search_distance=.12, groups={muscle.id: 'family'}), **guards)
            self.assertEqual(result['status'], 'success', result)
            self.assertEqual(configuration.read(root)['search_distance'], .12)
            self.assertEqual(muscle.get('af_pair_group_id'), 'family')
            result = call(root, journal, 'configure', configuration=dict(search_distance=.2), **guards)
            self.assertNotEqual(result['status'], 'success')

    def test_reopen_rebuilds_memory_and_preserves_geometry(self):
        root, _, muscle = fixture(); name, mid = root.name, muscle.id; before = mesh(root, muscle).copy()
        with configuration.transaction(root, dict(search_distance=.123, groups={mid: 'family'})): pass
        runtime.refresh(bpy.context.scene, root, True); finish(); epoch = runtime.COORDINATOR.epoch
        with TemporaryDirectory() as folder:
            path = str(Path(folder)/'pairs.blend'); bpy.ops.wm.save_as_mainfile(filepath=path); bpy.ops.wm.open_mainfile(filepath=path)
            root = bpy.data.objects[name]; muscle = next(m for m in root.af_vcp_system.muscles if m.id == mid)
            self.assertGreater(runtime.COORDINATOR.epoch, epoch); sleep(.16); finish()
            self.assertEqual(configuration.read(root)['search_distance'], .123)
            self.assertEqual(muscle.get('af_pair_group_id'), 'family')
            np.testing.assert_array_equal(mesh(root, muscle), before)
            self.assertEqual(runtime.inspect(bpy.context.scene, root)['status'], 'complete')

    def test_ui_defaults_and_display_change_are_not_detection_edits(self):
        root, _, _ = fixture(); props = root.af_pair_settings
        self.assertTrue(props.automatic); self.assertAlmostEqual(props.search, .05)
        runtime.refresh(bpy.context.scene, root, True); finish(); serial = runtime.COORDINATOR.serial
        runtime.notify(root, bpy.context.scene, event_type='SELECTION', full=True)
        self.assertEqual(runtime.COORDINATOR.serial, serial)
        props.automatic = False; self.assertEqual(runtime.inspect(bpy.context.scene, root)['status'], 'stale')
