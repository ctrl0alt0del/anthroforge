"""Application failure ownership and accepted output recovery."""
import unittest
from unittest.mock import patch
from test_muscle_control_consumption import MuscleControlConsumptionTests, inputs, runner, module


class ControlFailurePhaseTests(MuscleControlConsumptionTests):
    def reserve_output_request(self, independent=False, tail=False):
        value = self.queue_scoped_work({'MUSCLE': {self.muscle.id}} if independent else {})
        if tail:
            ctx, request = runner._resolve_item(runner._PENDING.pop())
            with patch.object(runner, '_RUNNING', True): runner._dispatch_runtime(ctx, request)
        return value

    def run_output_request(self, tail):
        if tail:
            return runner.sync_from_dirty_hints(self.root, self.scene, {}, full=False)
        return runner._flush_pending()

    def assert_output_failure(self, phase, independent=False, tail=False):
        value = self.reserve_output_request(independent, tail)
        with patch.object(self.sync, '_snapped_part_control', wraps=self.sync._snapped_part_control) as snap:
            with patch.object(module, phase, side_effect=RuntimeError('output failure')):
                with self.assertRaises(RuntimeError): self.run_output_request(tail)
        self.assertEqual(snap.call_count, 1); self.assertEqual(len(runner._PENDING), 1)
        record = inputs.input_record(value)
        self.assertEqual(record.handled, value.revision); self.assertIsNone(record.failed)
        self.assert_output_retry()

    def assert_output_retry(self):
        with patch.object(self.sync, '_snapped_part_control', wraps=self.sync._snapped_part_control) as snap:
            with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
                with patch.object(module, 'publish_muscle_work', wraps=module.publish_muscle_work) as publish:
                    runner._flush_pending()
        self.assertEqual((snap.call_count, numeric.call_count, publish.call_count), (0, 1, 1))
        self.assertFalse(runner._PENDING); self.assert_visible_authored()

    def test_numeric_control_only_retry_does_not_resnap(self):
        self.assert_output_failure('execute_muscle_work')

    def test_publication_control_only_retry_does_not_resnap(self):
        self.assert_output_failure('publish_muscle_work')

    def test_numeric_with_independent_work_keeps_request(self):
        self.assert_output_failure('execute_muscle_work', independent=True)

    def test_publication_with_independent_work_keeps_request(self):
        self.assert_output_failure('publish_muscle_work', independent=True)

    def test_nested_numeric_control_only_keeps_request(self):
        self.assert_output_failure('execute_muscle_work', tail=True)

    def test_nested_publication_control_only_keeps_request(self):
        self.assert_output_failure('publish_muscle_work', tail=True)

    def test_nested_numeric_with_independent_work_keeps_request(self):
        self.assert_output_failure('execute_muscle_work', independent=True, tail=True)

    def test_nested_publication_with_independent_work_keeps_request(self):
        self.assert_output_failure('publish_muscle_work', independent=True, tail=True)

    def fail_output_once(self, phase='execute_muscle_work', tail=False):
        self.reserve_output_request(tail=tail)
        with patch.object(module, phase, side_effect=RuntimeError('output failure')):
            with self.assertRaises(RuntimeError): self.run_output_request(tail)
        return runner._PENDING[0].request

    def test_automatic_timer_excludes_failed_output_and_stops(self):
        request = self.fail_output_once()
        self.assertEqual(request.progress.accepted_dirty, {'MUSCLE': {self.muscle.id}})
        with patch.object(module, 'execute_muscle_work') as numeric:
            self.assertIsNone(runner._timer_flush_pending())
        self.assertEqual(numeric.call_count, 0); self.assertEqual(len(runner._PENDING), 1)
        self.assert_output_retry(); self.assertFalse(request.progress.accepted_dirty)

    def assert_newer_after_failure(self, phase, tail=False):
        self.reserve_output_request(tail=tail)
        def failed(*args, **kwargs):
            self.notify(self.target(.3))
            raise RuntimeError('older output failed')
        with patch.object(module, phase, side_effect=failed):
            with self.assertRaises(RuntimeError): self.run_output_request(tail)
        self.assertEqual(len(runner._PENDING), 2)
        with patch.object(self.sync, '_snapped_part_control', wraps=self.sync._snapped_part_control) as snap:
            runner._timer_flush_pending()
        self.assertEqual(snap.call_count, 1); self.assertEqual(len(runner._PENDING), 1)
        current = tuple(self.ctrl.location)
        self.assert_output_retry(); self.assertEqual(tuple(self.ctrl.location), current)

    def test_newer_input_survives_numeric_failure(self):
        self.assert_newer_after_failure('execute_muscle_work')

    def test_newer_input_survives_publication_failure(self):
        self.assert_newer_after_failure('publish_muscle_work')

    def test_newer_input_survives_nested_tail_numeric_failure(self):
        self.assert_newer_after_failure('execute_muscle_work', tail=True)

    def test_newer_input_survives_nested_tail_publication_failure(self):
        self.assert_newer_after_failure('publish_muscle_work', tail=True)

    def assert_application_failure(self, owner, name, independent):
        value = self.reserve_output_request(independent=independent)
        with patch.object(owner, name, side_effect=RuntimeError('application failure')):
            with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
                runner._flush_pending()
        self.assertEqual(numeric.call_count, int(independent)); self.assertFalse(runner._PENDING)
        record = inputs.input_record(value)
        self.assertEqual(record.handled, 0); self.assertIsNotNone(record.failed)
        self.assertIsNone(inputs.reserve_input(self.root, self.scene, self.ctrl))
        runner.sync_from_dirty_hints(self.root, self.scene, {'MUSCLE': {self.muscle.id}}, full=False)
        self.assertIsNone(record.failed); self.assert_visible_authored()

    def test_snap_failure_keeps_independent_work(self):
        self.assert_application_failure(self.sync, '_snapped_part_control', True)

    def test_snap_failure_without_independent_work(self):
        self.assert_application_failure(self.sync, '_snapped_part_control', False)

    def test_conflict_failure_keeps_independent_work(self):
        self.assert_application_failure(module, 'resolve_conflict', True)

    def test_conflict_failure_without_independent_work(self):
        self.assert_application_failure(module, 'resolve_conflict', False)

    def test_setter_failure_keeps_independent_work(self):
        self.assert_application_failure(module, 'set_muscle_inflation_ctrl_world', True)

    def test_setter_failure_without_independent_work(self):
        self.assert_application_failure(module, 'set_muscle_inflation_ctrl_world', False)

    def test_setter_error_after_commit_publishes_accepted_impact(self):
        value = self.reserve_output_request()
        original = module.set_muscle_inflation_ctrl_world
        def setter(*args):
            original(*args)
            raise RuntimeError('after commit')
        with patch.object(module, 'set_muscle_inflation_ctrl_world', side_effect=setter):
            with patch.object(module, 'publish_muscle_work', wraps=module.publish_muscle_work) as publish:
                runner._flush_pending()
        self.assertEqual(publish.call_count, 1); self.assertFalse(runner._PENDING)
        self.assertEqual(inputs.input_record(value).handled, value.revision)
        self.assertIsNone(inputs.input_record(value).failed); self.assert_visible_authored()

    def test_request_progress_is_separate_and_cleared_after_publication(self):
        first = self.fail_output_once()
        self.reserve_output_request()
        second = runner._PENDING[-1].request
        self.assertIsNot(first.progress, second.progress)
        self.assertFalse(second.progress.accepted_dirty)
        runner._timer_flush_pending(); self.assertFalse(second.progress.accepted_dirty)
        self.assertTrue(first.progress.accepted_dirty)
        runner._flush_pending(); self.assertFalse(first.progress.accepted_dirty)

    def test_attempted_deferred_request_cannot_coalesce_away_progress(self):
        self.queue_scoped_work(source='depsgraph', event_type='SCP_UPDATE')
        runner._PENDING[0].due_at = 0
        with patch.object(module, 'execute_muscle_work', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError): runner._flush_pending()
        first = runner._PENDING[0]
        ctx, request = runner._resolve_item(first)
        runner._enqueue_item(ctx, request)
        self.assertEqual(len(runner._PENDING), 2)
        self.assertIs(runner._PENDING[0], first); self.assertTrue(first.request.progress.accepted_dirty)

    def test_immediate_numeric_failure_retains_accepted_work(self):
        self.reserve_output_request()
        ctx, request = runner._resolve_item(runner._PENDING.pop())
        with patch.object(module, 'execute_muscle_work', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError): runner._dispatch_runtime(ctx, request)
        self.assertEqual(len(runner._PENDING), 1); self.assert_output_retry()

    def test_numeric_error_result_retains_accepted_impact(self):
        from dataclasses import replace
        original = module.execute_muscle_work
        def invalid(*args):
            batch = original(*args)
            return replace(batch, results=tuple(replace(row, error='injected invalid result') for row in batch.results))
        self.reserve_output_request()
        with patch.object(module, 'execute_muscle_work', side_effect=invalid):
            with self.assertRaisesRegex(RuntimeError, 'awaits publication'): runner._flush_pending()
        self.assertEqual(len(runner._PENDING), 1)
        self.assertTrue(runner._PENDING[0].request.progress.accepted_dirty)
        self.assert_output_retry()

    def test_publication_busy_return_retains_accepted_impact(self):
        self.reserve_output_request()
        with patch.object(self.sync, 'sync_root_to_scene', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'awaits publication'): runner._flush_pending()
        self.assertEqual(len(runner._PENDING), 1); self.assert_output_retry()

    def test_pending_request_does_not_retain_application_tracebacks(self):
        self.reserve_output_request(independent=True)
        with patch.object(self.sync, '_snapped_part_control', side_effect=RuntimeError('application')):
            with patch.object(module, 'execute_muscle_work', side_effect=RuntimeError('numeric')):
                with self.assertRaisesRegex(RuntimeError, 'numeric'): runner._flush_pending()
        self.assertEqual(len(runner._PENDING), 1)
        self.assertFalse(runner._PENDING[0].request.progress.application_errors)
        runner._flush_pending(); self.assertFalse(runner._PENDING); self.assert_visible_authored()

    def test_deleted_owner_rejects_failed_output_retry(self):
        import bpy
        self.fail_output_once()
        bpy.data.objects.remove(self.root, do_unlink=True)
        with patch.object(module, 'execute_muscle_work') as numeric:
            runner._flush_pending()
        self.assertEqual(numeric.call_count, 0); self.assertFalse(runner._PENDING)

    def test_immediate_publication_failure_retains_accepted_work(self):
        self.reserve_output_request()
        ctx, request = runner._resolve_item(runner._PENDING.pop())
        with patch.object(module, 'publish_muscle_work', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError): runner._dispatch_runtime(ctx, request)
        self.assertEqual(len(runner._PENDING), 1); self.assert_output_retry()

    def test_error_result_without_accepted_input_preserves_status_policy(self):
        from dataclasses import replace
        original = module.execute_muscle_work
        def invalid(*args):
            batch = original(*args)
            return replace(batch, results=tuple(replace(row, error='injected invalid result') for row in batch.results))
        runner.schedule_sync_from_dirty_hints(self.root, self.scene, {'MUSCLE': {self.muscle.id}}, full=False)
        with patch.object(module, 'execute_muscle_work', side_effect=invalid): runner._flush_pending()
        self.assertFalse(runner._PENDING)


def load_tests(loader, tests, pattern):
    names = [name for name in ControlFailurePhaseTests.__dict__ if name.startswith('test_')]
    return unittest.TestSuite(ControlFailurePhaseTests(name) for name in sorted(names))
