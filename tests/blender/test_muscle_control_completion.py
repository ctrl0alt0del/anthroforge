"""AF-16 complete publication and transport-independent owner authority."""
import unittest
from unittest.mock import patch
import bpy
from test_muscle_control_failure_phases import ControlFailurePhaseTests
from test_muscle_control_consumption import inputs, runner, module
from anthroforge.core.deps import builtin_drivers, controls, drivers, runtime
from anthroforge.core.visualization import vcp_mirror_runtime as mirrors
from anthroforge.core.visualization.mirror_rules import mirror_world_matrix


class ControlCompletionTests(ControlFailurePhaseTests):
    def enable_mirrors(self):
        for fiber in self.root.af_vcp_system.fibers:
            fiber['af_authoring_symmetry'] = 'native_mirror'
            fiber['af_authoring_mirror_axis'] = 'X'
            fiber['af_authoring_mirror_origin'] = (0., 0., 0.)

    def assert_source_and_mirror(self):
        collection = bpy.data.collections.get(self.sync.collection_name)
        for surface in ('BASE', 'INFL'):
            source = mirrors._find_source_muscle_obj(collection, self.root.name, self.muscle.id, surface)
            mirrored = mirrors._find_mirror_muscle_obj(collection, self.root.name, self.muscle.id, surface)
            self.assertIsNotNone(mirrored); self.assertEqual(source.get('af_muscle_output_state'), 'CURRENT')
            self.assertGreater(len(source.data.vertices), 0); self.assertEqual(source.data, mirrored.data)
            expected = mirror_world_matrix(source.matrix_world)
            self.assertLess(max(abs(a-b) for x,y in zip(expected, mirrored.matrix_world) for a,b in zip(x,y)), 1e-7)

    def assert_completion_failure(self, owner, name, independent=False):
        self.enable_mirrors(); self.reserve_output_request(independent=independent)
        with patch.object(owner, name, side_effect=RuntimeError('downstream failure')):
            with self.assertRaises(RuntimeError): runner._flush_pending()
        request = runner._PENDING[0].request
        self.assertEqual(request.progress.accepted_dirty, {'MUSCLE': {self.muscle.id}})
        with patch.object(builtin_drivers, 'sync_vcp_mirrors', wraps=builtin_drivers.sync_vcp_mirrors) as mirror:
            self.assert_output_retry()
        self.assertEqual(mirror.call_count, 1); self.assert_source_and_mirror()
        self.assertFalse(request.progress.accepted_dirty)

    def test_source_success_mirror_failure_retains_impact(self):
        self.assert_completion_failure(builtin_drivers, 'sync_vcp_mirrors')

    def test_source_success_downstream_driver_failure_retains_impact(self):
        self.assert_completion_failure(builtin_drivers.BlobSyncDriver, 'sync')

    def test_source_and_mirror_success_post_sync_failure_retains_impact(self):
        self.assert_completion_failure(drivers.DependencyDriver, 'post_sync')

    def test_source_and_mirror_success_notification_failure_retains_impact(self):
        self.assert_completion_failure(runtime, '_notify_warnings')

    def test_downstream_failure_preserves_independent_work(self):
        self.assert_completion_failure(builtin_drivers, 'sync_vcp_mirrors', independent=True)

    def start_legacy_input(self, failed_input=False):
        if failed_input:
            with patch.object(self.sync, '_snapped_part_control', side_effect=RuntimeError('snap')):
                with self.assertRaises(RuntimeError): self.observe(self.target(.4))
        else:
            self.ctrl.location = self.target(.4)
            self.assertTrue(controls.enqueue_control_intent(self.root, 'MUSCLE_INFLATION', {'object_name': self.ctrl.name}))

    def retain_legacy_work(self, failed_input=False, deferred=False):
        self.start_legacy_input(failed_input)
        if deferred: runner.schedule_sync_from_dirty_hints(self.root, self.scene, {}, full=False)
        with patch.object(module, 'execute_muscle_work', side_effect=RuntimeError('numeric')):
            with self.assertRaises(RuntimeError):
                if deferred: runner._flush_pending()
                else: runner.sync_from_dirty_hints(self.root, self.scene, {}, full=False)
        self.assertEqual(len(runner._PENDING), 1)
        return runner._PENDING[0]

    def rename_and_replace_root(self):
        old_name = self.root.name
        self.root.name = 'OriginalRenamed'
        replacement = bpy.data.objects.new(old_name, None)
        self.scene.collection.objects.link(replacement)
        return replacement

    def assert_original_retry(self, failed_input=False, deferred=False):
        item = self.retain_legacy_work(failed_input, deferred)
        replacement = self.rename_and_replace_root()
        with patch.object(runner, 'run_dependency_runtime', wraps=runner.run_dependency_runtime) as run:
            with self.assertRaisesRegex(RuntimeError, 'awaits publication'): runner._flush_pending()
        self.assertTrue(item.request.progress.accepted_dirty)
        self.assertEqual(run.call_args.kwargs['root'], self.root)
        self.assertNotEqual(run.call_args.kwargs['root'], replacement)
        self.assertTrue(item.owner_ids)
        runner.sync_from_dirty_hints(self.root, self.scene, {}, full=True)
        self.assert_output_retry()

    def test_legacy_accepted_retry_preserves_renamed_original(self):
        self.assert_original_retry()

    def test_deferred_legacy_accepted_retry_preserves_renamed_original(self):
        self.assert_original_retry(deferred=True)

    def test_failed_input_retry_preserves_renamed_original(self):
        self.assert_original_retry(failed_input=True)

    def test_deferred_failed_input_retry_preserves_renamed_original(self):
        self.assert_original_retry(failed_input=True, deferred=True)

    def assert_deleted_owner_rejected(self, failed_input=False, deferred=False):
        self.retain_legacy_work(failed_input, deferred)
        self.rename_and_replace_root()
        bpy.data.objects.remove(self.root, do_unlink=True)
        with patch.object(runner, 'run_dependency_runtime') as run: runner._flush_pending()
        self.assertEqual(run.call_count, 0); self.assertFalse(runner._PENDING)

    def test_legacy_deleted_owner_cannot_retarget_replacement(self):
        self.assert_deleted_owner_rejected()

    def test_failed_input_deleted_owner_cannot_retarget_replacement(self):
        self.assert_deleted_owner_rejected(failed_input=True)

    def test_deferred_legacy_deleted_owner_cannot_retarget_replacement(self):
        self.assert_deleted_owner_rejected(deferred=True)

    def test_deferred_failed_input_deleted_owner_cannot_retarget_replacement(self):
        self.assert_deleted_owner_rejected(failed_input=True, deferred=True)

    def test_legacy_queued_before_acceptance_uses_original_owner(self):
        self.start_legacy_input()
        runner.schedule_sync_from_dirty_hints(self.root, self.scene, {}, full=False)
        self.rename_and_replace_root()
        with patch.object(runner, 'run_dependency_runtime', wraps=runner.run_dependency_runtime) as run:
            runner._flush_pending()
        self.assertEqual(run.call_args.kwargs['root'], self.root)
        self.assertTrue(all(item.owner_refs == (self.scene, self.root) for item in runner._PENDING))

    def test_failed_attempt_cannot_lend_source_receipt_to_retry(self):
        self.reserve_output_request()
        with patch.object(builtin_drivers, 'sync_vcp_mirrors', side_effect=RuntimeError('mirror')):
            with self.assertRaises(RuntimeError): runner._flush_pending()
        request = runner._PENDING[0].request
        self.assertEqual(request.progress.published_muscles, {self.muscle.id})
        with patch.object(self.sync, 'sync_root_to_scene', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'awaits publication'): runner._flush_pending()
        self.assertTrue(request.progress.accepted_dirty); self.assertFalse(request.progress.published_muscles)
        self.assert_output_retry()

    def test_no_envelope_independent_work_retries_downstream_failure(self):
        self.enable_mirrors()
        runner.schedule_sync_from_dirty_hints(self.root, self.scene, {'MUSCLE': {self.muscle.id}}, full=False)
        with patch.object(builtin_drivers, 'sync_vcp_mirrors', side_effect=RuntimeError('mirror')):
            with self.assertRaises(RuntimeError): runner._flush_pending()
        self.assertEqual(len(runner._PENDING), 1)
        self.assert_output_retry(); self.assert_source_and_mirror()

    def test_newer_input_survives_older_mirror_failure(self):
        self.enable_mirrors(); self.reserve_output_request()
        def fail(*args, **kwargs):
            self.notify(self.target(.3))
            raise RuntimeError('mirror')
        with patch.object(builtin_drivers, 'sync_vcp_mirrors', side_effect=fail):
            with self.assertRaises(RuntimeError): runner._flush_pending()
        self.assertEqual(len(runner._PENDING), 2)
        runner._timer_flush_pending(); self.assertEqual(len(runner._PENDING), 1)
        point = tuple(self.ctrl.location)
        self.assert_output_retry(); self.assertEqual(tuple(self.ctrl.location), point)
        self.assert_source_and_mirror()

    def test_legacy_scene_rename_preserves_authority(self):
        item = self.retain_legacy_work()
        name = self.scene.name; self.scene.name = 'RenamedScene'
        bpy.data.scenes.new(name)
        self.assertEqual(runner._resolve_item(item)[0].scene, self.scene)
        self.assert_output_retry()

    def test_legacy_deleted_scene_rejects_replacement(self):
        item = self.retain_legacy_work()
        old = self.scene; name = old.name; old.name = 'DeletedScene'
        replacement = bpy.data.scenes.new(name)
        bpy.context.window.scene = replacement
        bpy.data.scenes.remove(old)
        with patch.object(runner, 'run_dependency_runtime') as run: runner._flush_pending()
        self.assertEqual(run.call_count, 0); self.assertFalse(runner._PENDING)


def load_tests(loader, tests, pattern):
    names = [name for name in ControlCompletionTests.__dict__ if name.startswith('test_')]
    return unittest.TestSuite(ControlCompletionTests(name) for name in sorted(names))
