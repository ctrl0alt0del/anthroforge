"""AF-16 real control application, FIFO reentry and lifecycle regressions."""
from types import SimpleNamespace as NS
from unittest.mock import patch

import bpy
from mathutils import Vector

from _helpers import BlenderTestCase
from test_muscle_inflation_persistence import _setup, _select, _control
from anthroforge.core.deps import muscle_control_intents as inputs
from anthroforge.core.deps.conflict_resolver import set_conflict_policy, clear_conflict_policies
from anthroforge.core.deps.controls import enqueue_control_intent
from anthroforge.core.vcp.runtime_state import muscle_inflation_ctrl_world
from anthroforge.core.visualization import muscle_sync as module, sync_runner as runner


class MuscleControlConsumptionTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        self.root = _setup(); _select(self.root, True)
        self.scene, self.sync = bpy.context.scene, module.register_muscle_sync()
        self.muscle = self.root.af_vcp_system.muscles[0]
        self.ctrl = _control(self.muscle)
        bpy.context.view_layer.update()
        runner.clear_pending_runtime(keep_timer=False)

    def tearDown(self):
        clear_conflict_policies()
        runner.clear_pending_runtime(keep_timer=False)
        super().tearDown()

    def observe(self, point):
        self.ctrl.location = point
        value = inputs.reserve_input(self.root, self.scene, self.ctrl)
        inputs.dispatch_input(self.root, self.scene, value)
        return value

    def notify(self, point):
        self.ctrl.location = point
        self.sync.on_depsgraph_update(self.scene, NS(updates=[NS(id=self.ctrl)]))

    def target(self, offset=.2):
        return self.ctrl.location + Vector((offset, 0., .03))

    def assert_visible_authored(self):
        self.assertLess((self.ctrl.location - Vector(muscle_inflation_ctrl_world(self.muscle))).length, 1e-7)

    def test_ordinary_once_duplicate_zero_and_no_fiber_work(self):
        with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
            with patch.object(module, 'publish_muscle_work', wraps=module.publish_muscle_work) as publish:
                self.observe(self.target()); self.assertEqual((numeric.call_count, publish.call_count), (1, 1))
                self.assertIsNone(inputs.reserve_input(self.root, self.scene, self.ctrl))
                bpy.context.view_layer.update()
                self.assertEqual((numeric.call_count, publish.call_count), (1, 1))
        self.assert_visible_authored()

    def test_actual_translate_consumes_evaluated_control_once(self):
        for obj in bpy.context.selected_objects: obj.select_set(False)
        self.ctrl.select_set(True); bpy.context.view_layer.objects.active = self.ctrl
        with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
            self.assertEqual(bpy.ops.transform.translate(value=(.2, 0., .03)), {'FINISHED'})
            bpy.context.view_layer.update()
        self.assertEqual(numeric.call_count, 1); self.assert_visible_authored()

    def test_prefer_domain_restores_without_numeric_or_publication(self):
        previous = tuple(self.ctrl.location)
        set_conflict_policy('prefer_domain', entity_type='MUSCLE', aspect='inflation.ctrl_world')
        with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
            with patch.object(module, 'publish_muscle_work', wraps=module.publish_muscle_work) as publish:
                self.observe(self.target())
                self.assertEqual((numeric.call_count, publish.call_count), (0, 0))
        self.assertEqual(tuple(self.ctrl.location), previous)
        self.assert_visible_authored()

    def test_conflict_newer_input_survives_fifo(self):
        original, seen = self.sync._resolved_ctrl_world, []
        def resolve(mid, part, point):
            seen.append(point)
            if len(seen) == 1:
                self.notify(self.target(.35))
            return original(mid, part, point)
        with patch.object(self.sync, '_resolved_ctrl_world', side_effect=resolve):
            with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
                self.observe(self.target())
                self.assertEqual(numeric.call_count, 2)
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0], seen[1]); self.assert_visible_authored()

    def test_acquisition_reserves_newer_and_claims_direct_once(self):
        original, seen = inputs.acquire_graph, []
        def acquire(root, scene):
            seen.append('acquire'); self.notify(tuple(self.ctrl.location))
            if len(seen) == 1: self.notify(self.target(.3))
            return original(root, scene)
        self.ctrl.location = self.target()
        with patch.object(inputs, 'acquire_graph', side_effect=acquire):
            changed = module.apply_muscle_control_update(self.sync, self.root, self.scene, self.ctrl)
        self.assertEqual(changed, self.muscle.id)
        self.assertEqual(len(seen), 1)
        self.assertEqual(len(runner._PENDING), 1)
        while runner._PENDING: runner._flush_pending()
        self.assert_visible_authored()

    def test_publication_observes_unnotified_newer_transform(self):
        original, calls = module.publish_muscle_work, []
        def publish(*args):
            calls.append(1)
            if len(calls) == 1: self.ctrl.location = self.target(.3)
            return original(*args)
        with patch.object(module, 'publish_muscle_work', side_effect=publish):
            self.observe(self.target())
        self.assertEqual(len(calls), 2); self.assert_visible_authored()

    def test_setter_newer_transform_survives(self):
        original, calls = module.set_muscle_inflation_ctrl_world, []
        def setter(part, point):
            calls.append(point)
            if len(calls) == 1: self.notify(self.target(.3))
            return original(part, point)
        with patch.object(module, 'set_muscle_inflation_ctrl_world', side_effect=setter):
            self.observe(self.target())
        self.assertEqual(len(calls), 2); self.assert_visible_authored()

    def test_failure_retries_explicitly_and_duplicate_does_not(self):
        with patch.object(self.sync, '_snapped_part_control', side_effect=RuntimeError('expected')):
            with self.assertRaises(RuntimeError): self.observe(self.target())
        record = next(iter(inputs._RECORDS.values()))
        self.assertIsNotNone(record.failed); self.assertEqual(record.handled, 0)
        self.assertIsNone(inputs.reserve_input(self.root, self.scene, self.ctrl))
        runner.sync_from_dirty_hints(self.root, self.scene, {'MUSCLE': {self.muscle.id}}, full=False)
        self.assertIsNone(record.failed); self.assert_visible_authored()

    def test_noop_keeps_independent_dirty_hint(self):
        set_conflict_policy('prefer_domain', entity_type='MUSCLE', aspect='inflation.ctrl_world')
        self.ctrl.location = self.target()
        value = inputs.reserve_input(self.root, self.scene, self.ctrl)
        with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
            runner.sync_from_dirty_hints(self.root, self.scene, {'MUSCLE': {self.muscle.id}},
                                         full=False, payload={'muscle_control_input': value})
        self.assertEqual(numeric.call_count, 1); self.assert_visible_authored()

    def test_legacy_queue_freezes_distinct_inputs(self):
        points = [self.target(.2), self.target(.4), self.target(.2)]
        for point in points:
            self.ctrl.location = point
            self.assertTrue(enqueue_control_intent(self.root, 'MUSCLE_INFLATION', {'object_name': self.ctrl.name}))
        with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
            runner.sync_from_dirty_hints(self.root, self.scene, {}, full=False)
        self.assertEqual(numeric.call_count, 3); self.assert_visible_authored()

    def test_history_retires_pending_and_mode_rebind_does_not_apply(self):
        self.ctrl.location = self.target()
        value = inputs.reserve_input(self.root, self.scene, self.ctrl)
        runner._on_history_pre(None)
        self.assertIsNone(inputs.input_record(value))
        self.assertIsNone(module.apply_muscle_control_update(self.sync, self.root, self.scene, self.ctrl, value))


    def test_tail_overflow_keeps_fifo_when_new_input_arrives(self):
        original, points = self.sync._resolved_ctrl_world, []
        def resolve(mid, part, point):
            points.append(point)
            if len(points) == 1:
                for index in range(7): self.notify(self.target(.04))
            return original(mid, part, point)
        with patch.object(self.sync, '_resolved_ctrl_world', side_effect=resolve):
            self.observe(self.target())
            self.assertEqual(len(points), 5)
            self.observe(self.target(.1))
            self.assertEqual(len(points), 5)
            while runner._PENDING: runner._flush_pending()
        self.assertEqual(len(points), 9); self.assert_visible_authored()

    def test_failed_deferred_input_does_not_block_newer_input(self):
        self.ctrl.location = self.target()
        value = inputs.reserve_input(self.root, self.scene, self.ctrl)
        inputs.dispatch_input(self.root, self.scene, value, deferred=True)
        with patch.object(self.sync, '_snapped_part_control', side_effect=RuntimeError('expected deferred failure')):
            runner._flush_pending()
        self.assertFalse(runner._PENDING)
        self.observe(self.target(.3)); self.assert_visible_authored()
        self.assertIsNone(next(iter(inputs._RECORDS.values())).failed)

    def test_queued_rename_uses_identity_and_recreation_rejects(self):
        self.ctrl.location = self.target()
        value = inputs.reserve_input(self.root, self.scene, self.ctrl)
        inputs.dispatch_input(self.root, self.scene, value, deferred=True)
        old = self.ctrl.name; self.ctrl.name = 'RenamedControl'
        other = bpy.data.objects.new(old, None); self.scene.collection.objects.link(other)
        runner._flush_pending(); self.assert_visible_authored()
        self.assertEqual(tuple(other.location), (0., 0., 0.))
        bpy.data.objects.remove(self.ctrl, do_unlink=True)
        inputs.prune_inputs(); self.assertFalse(inputs._RECORDS)
        self.assertIsNone(inputs.input_record(value))

    def test_duplicate_legacy_dispatch_keeps_only_explicit_dirty(self):
        from anthroforge.core.deps.runtime_intents import dispatch_runtime_intent
        options = dict(root=self.root, scene=self.scene, intent_type='CONTROL/MUSCLE_INFLATION',
                       entity_type='MUSCLE', entity_id=self.muscle.id, payload={'object_name': self.ctrl.name})
        with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
            dispatch_runtime_intent(**options); self.assertEqual(numeric.call_count, 0)
            dispatch_runtime_intent(**options, dirty_hints={'MUSCLE': {self.muscle.id}})
            self.assertEqual(numeric.call_count, 1)

    def test_dependent_retry_and_unrelated_dependency_does_not_retry(self):
        with patch.object(self.sync, '_snapped_part_control', side_effect=RuntimeError('expected')):
            with self.assertRaises(RuntimeError): self.observe(self.target())
        record = next(iter(inputs._RECORDS.values()))
        with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
            runner.sync_from_dirty_hints(self.root, self.scene, {'SCP': {'missing'}}, full=False, source='depsgraph')
            self.assertEqual(numeric.call_count, 0); self.assertIsNotNone(record.failed)
        runner.sync_from_dirty_hints(self.root, self.scene, {'MUSCLE': {self.muscle.id}}, full=False, source='property')
        self.assertIsNone(record.failed); self.assert_visible_authored()

    def test_cancel_restored_coordinates_are_one_distinct_input(self):
        original = tuple(self.ctrl.location)
        self.observe(self.target())
        with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
            self.observe(original); self.assertEqual(numeric.call_count, 1)
            self.assertIsNone(inputs.reserve_input(self.root, self.scene, self.ctrl))
        self.assert_visible_authored()
        self.assertLess((self.ctrl.location - Vector(original)).length, 1e-7)


    def test_source_mutation_defers_snap_until_fresh_context(self):
        original, calls = self.sync._resolved_ctrl_world, []
        def resolve(mid, part, point):
            calls.append(point)
            if len(calls) == 1:
                runner.sync_from_dirty_hints(self.root, self.scene, {'SCP': {'missing'}}, full=False)
            return original(mid, part, point)
        with patch.object(self.sync, '_resolved_ctrl_world', side_effect=resolve):
            with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
                self.observe(self.target()); self.assertEqual(numeric.call_count, 0)
                self.assertEqual(len(runner._PENDING), 1)
                runner._flush_pending(); self.assertEqual(numeric.call_count, 1)
        self.assertEqual(len(calls), 2); self.assert_visible_authored()

    def test_snap_echo_is_duplicate_and_newer_point_is_queued(self):
        original, calls = self.sync._snapped_part_control, []
        def snap(*args):
            calls.append(args[3].point)
            self.notify(tuple(self.ctrl.location))
            if len(calls) == 1: self.notify(self.target(.3))
            return original(*args)
        with patch.object(self.sync, '_snapped_part_control', side_effect=snap):
            self.observe(self.target())
        self.assertEqual(len(calls), 2); self.assert_visible_authored()


    def test_source_invalidation_after_newer_queue_preserves_fifo(self):
        original, calls = self.sync._resolved_ctrl_world, []
        def resolve(mid, part, point):
            calls.append(point)
            if len(calls) == 1:
                self.notify(self.target(.3))
                runner.sync_from_dirty_hints(self.root, self.scene, {'SCP': {'missing'}}, full=False)
            return original(mid, part, point)
        with patch.object(self.sync, '_resolved_ctrl_world', side_effect=resolve):
            with patch.object(self.sync, '_accept_control', wraps=self.sync._accept_control) as accept:
                self.observe(self.target())
                while runner._PENDING: runner._flush_pending()
        self.assertEqual([row.args[3].revision for row in accept.call_args_list], [1, 2])


    def test_direct_source_invalidation_keeps_queued_newer_input_in_order(self):
        original, calls = self.sync._resolved_ctrl_world, []
        def resolve(mid, part, point):
            calls.append(point)
            if len(calls) == 1:
                self.notify(self.target(.3))
                runner.sync_from_dirty_hints(self.root, self.scene, {'SCP': {'missing'}}, full=False)
            return original(mid, part, point)
        with patch.object(self.sync, '_resolved_ctrl_world', side_effect=resolve):
            with patch.object(self.sync, '_accept_control', wraps=self.sync._accept_control) as accept:
                self.ctrl.location = self.target()
                module.apply_muscle_control_update(self.sync, self.root, self.scene, self.ctrl)
                while runner._PENDING: runner._flush_pending()
        self.assertEqual([row.args[3].revision for row in accept.call_args_list], [1, 2])


    def test_context_retry_preserves_order_without_starving_other_root(self):
        self.assert_context_retry_order((1., 2., 3.))

    def test_equal_deadline_retry_preserves_unrelated_arrival_order(self):
        self.assert_context_retry_order((1., 1., 1.))

    def test_source_invalidation_fifo_across_tail_overflow(self):
        with patch.object(runner, '_MAX_TAIL_PASSES', 0):
            self.test_source_invalidation_after_newer_queue_preserves_fifo()

    def test_wait_uses_older_input_deadline_instead_of_blocked_newer(self):
        self.ctrl.location = self.target(); a = inputs.reserve_input(self.root, self.scene, self.ctrl)
        self.ctrl.location = self.target(.3); b = inputs.reserve_input(self.root, self.scene, self.ctrl)
        self.defer_at(b, 1.); self.defer_at(a, 3.)
        self.assertIsNone(runner._ready_index(2.))
        self.assertEqual(runner._next_delay(2.), 1.)

    def test_failed_older_input_releases_already_queued_newer(self):
        self.ctrl.location = self.target(); a = inputs.reserve_input(self.root, self.scene, self.ctrl)
        self.ctrl.location = self.target(.3); b = inputs.reserve_input(self.root, self.scene, self.ctrl)
        self.defer_at(b, 1.); self.defer_at(a, 2.)
        with patch.object(self.sync, '_snapped_part_control', side_effect=RuntimeError('expected older failure')):
            runner._flush_pending()
        self.assertEqual(len(runner._PENDING), 1)
        runner._flush_pending(); self.assert_visible_authored()
        record = next(iter(inputs._RECORDS.values()))
        self.assertEqual(record.handled, b.revision); self.assertIsNone(record.failed)

    def assert_context_retry_order(self, deadlines):
        other = bpy.data.objects.new('OtherRoot', None); self.scene.collection.objects.link(other)
        self.ctrl.location = self.target(); a = inputs.reserve_input(self.root, self.scene, self.ctrl)
        self.ctrl.location = self.target(.3); b = inputs.reserve_input(self.root, self.scene, self.ctrl)
        self.defer_at(b, deadlines[0])
        with patch.object(runner, '_now', return_value=deadlines[1]):
            runner.schedule_sync_from_dirty_hints(other, self.scene, {}, full=False, source='unrelated')
        self.defer_at(a, deadlines[2])
        with patch.object(runner, '_run_one_request', wraps=runner._run_one_request) as run:
            while runner._PENDING: runner._flush_pending()
        values = [getattr(row.args[1].payload.get('muscle_control_input'), 'revision', None) for row in run.call_args_list]
        self.assertEqual(values, [None, 1, 2]); self.assert_visible_authored()

    def defer_at(self, value, when):
        with patch.object(runner, '_now', return_value=when):
            inputs.dispatch_input(self.root, self.scene, value, fresh_context=True)

    def test_distinct_control_identities_do_not_merge_tail_requests(self):
        other = self.ctrl.copy(); self.scene.collection.objects.link(other)
        self.ctrl.location = self.target(); a = inputs.reserve_input(self.root, self.scene, self.ctrl)
        other.location = self.target(.3); b = inputs.reserve_input(self.root, self.scene, other)
        with patch.object(runner, '_RUNNING', True):
            inputs.dispatch_input(self.root, self.scene, a)
            inputs.dispatch_input(self.root, self.scene, b)
        self.assertEqual(len(runner._TAIL_PENDING), 2)
        self.assertNotEqual(runner._runtime_key(*runner._TAIL_PENDING[0]), runner._runtime_key(*runner._TAIL_PENDING[1]))

    def test_rebinding_during_callbacks_rejects_old_input(self):
        for owner, name in ((inputs, 'acquire_graph'), (self.sync, '_snapped_part_control'),
                            (self.sync, '_resolved_ctrl_world')):
            with self.subTest(callback=name):
                self.assert_callback_rebinding(owner, name)

    def assert_callback_rebinding(self, owner, name):
        original, previous = getattr(owner, name), muscle_inflation_ctrl_world(self.muscle)
        def mutate(*args):
            result = original(*args); self.ctrl['af_inflation_side'] = 'B'
            return result
        self.ctrl['af_inflation_side'] = 'A'; inputs.reset_control_inputs()
        self.ctrl.location = self.target()
        with patch.object(owner, name, side_effect=mutate):
            self.assertIsNone(module.apply_muscle_control_update(self.sync, self.root, self.scene, self.ctrl))
        self.assertEqual(muscle_inflation_ctrl_world(self.muscle), previous)

    def test_deletion_inside_setter_prevents_stale_visible_write(self):
        original = module.set_muscle_inflation_ctrl_world
        def setter(part, point):
            original(part, point); bpy.data.objects.remove(self.ctrl, do_unlink=True)
        self.ctrl.location = self.target()
        with patch.object(module, 'set_muscle_inflation_ctrl_world', side_effect=setter):
            changed = module.apply_muscle_control_update(self.sync, self.root, self.scene, self.ctrl)
        self.assertEqual(changed, self.muscle.id)
        self.assertFalse(inputs._RECORDS)

    def test_rebinding_inside_setter_preserves_distinct_visible_point(self):
        original, marker = module.set_muscle_inflation_ctrl_world, tuple(self.target(.4))
        def setter(part, point):
            original(part, point); self.ctrl['af_inflation_side'] = 'B'; self.ctrl.location = marker
        self.ctrl.location = self.target()
        with patch.object(module, 'set_muscle_inflation_ctrl_world', side_effect=setter):
            changed = module.apply_muscle_control_update(self.sync, self.root, self.scene, self.ctrl)
        self.assertEqual(changed, self.muscle.id)
        self.assertEqual(tuple(self.ctrl.location), marker)

    def rebound_input(self):
        from anthroforge.core.visualization.muscle_numeric_runtime import _bind_control
        previous = tuple(muscle_inflation_ctrl_world(self.muscle))
        self.ctrl.location = self.target(.4)
        old = inputs.reserve_input(self.root, self.scene, self.ctrl)
        inputs.dispatch_input(self.root, self.scene, old, deferred=True)
        collection = bpy.data.collections.get(self.sync.collection_name)
        _bind_control(self.sync, collection, self.root, self.muscle.id, '', 'B')
        self.assertIsNone(inputs.input_record(old))
        _bind_control(self.sync, collection, self.root, self.muscle.id, '', 'A')
        self.assertTrue(inputs.write_control(self.root, self.scene, self.ctrl, previous))
        return old, previous

    def test_return_to_same_side_does_not_revive_queued_input(self):
        old, previous = self.rebound_input()
        self.assertIsNone(inputs.input_record(old))
        with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
            runner._flush_pending()
        self.assertEqual(numeric.call_count, 0)
        self.assertEqual(tuple(muscle_inflation_ctrl_world(self.muscle)), previous)
        self.assertEqual(tuple(self.ctrl.location), previous)

    def test_old_lifetime_neither_merges_nor_blocks_new_movement(self):
        old, _ = self.rebound_input()
        self.ctrl.location = self.target(.2)
        new = inputs.reserve_input(self.root, self.scene, self.ctrl)
        self.assertNotEqual(inputs.input_key(old), inputs.input_key(new))
        self.assertFalse(runner.control_input_pending(new))
        with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
            inputs.dispatch_input(self.root, self.scene, new)
            runner._flush_pending()
        self.assertEqual(numeric.call_count, 1); self.assert_visible_authored()

    def test_old_lifetime_cannot_write_into_rebound_control(self):
        old, previous = self.rebound_input()
        self.assertFalse(inputs.write_control(self.root, self.scene, self.ctrl, old.point, old))
        self.assertEqual(tuple(self.ctrl.location), previous)

    def test_old_lifetime_does_not_block_higher_new_revision(self):
        old, _ = self.rebound_input()
        self.ctrl.location = self.target(.1)
        inputs.reserve_input(self.root, self.scene, self.ctrl)
        self.ctrl.location = self.target(.2)
        new = inputs.reserve_input(self.root, self.scene, self.ctrl)
        self.assertGreater(new.revision, old.revision)
        self.assertFalse(runner.control_input_pending(new))
        inputs.dispatch_input(self.root, self.scene, new)
        self.assertEqual(inputs.input_record(new).handled, new.revision)
        runner._flush_pending(); self.assert_visible_authored()

    def test_tail_queue_keeps_same_revision_different_lifetimes_distinct(self):
        old, _ = self.rebound_input()
        self.ctrl.location = self.target(.2)
        new = inputs.reserve_input(self.root, self.scene, self.ctrl)
        self.assertEqual(old.revision, new.revision)
        with patch.object(runner, '_RUNNING', True):
            inputs.dispatch_input(self.root, self.scene, old)
            inputs.dispatch_input(self.root, self.scene, new)
        self.assertEqual(len(runner._TAIL_PENDING), 2)
        self.assertNotEqual(runner._runtime_key(*runner._TAIL_PENDING[0]), runner._runtime_key(*runner._TAIL_PENDING[1]))

    def test_acquisition_rebinding_to_same_side_retires_inflight_input(self):
        original, seen = inputs.acquire_graph, []
        def acquire(root, scene):
            graph = original(root, scene)
            seen.append(self.rebound_input())
            return graph
        self.ctrl.location = self.target()
        with patch.object(inputs, 'acquire_graph', side_effect=acquire):
            self.assertIsNone(module.apply_muscle_control_update(self.sync, self.root, self.scene, self.ctrl))
        self.assertEqual(len(seen), 1)
        runner._flush_pending(); self.assert_visible_authored()

    def queue_scoped_work(self, dirty=None, full=False, **options):
        self.ctrl.location = self.target(.4)
        value = inputs.reserve_input(self.root, self.scene, self.ctrl)
        payload = dict(options.pop('payload', {}), muscle_control_input=value)
        runner.schedule_sync_from_dirty_hints(self.root, self.scene, dirty or {}, full=full, payload=payload, **options)
        return value

    def retire_scoped_control(self):
        from anthroforge.core.visualization.muscle_numeric_runtime import _bind_control
        collection = bpy.data.collections.get(self.sync.collection_name)
        _bind_control(self.sync, collection, self.root, self.muscle.id, '', 'B')

    def test_retired_control_preserves_independent_dirty_work(self):
        value = self.queue_scoped_work({'MUSCLE': {self.muscle.id}})
        self.retire_scoped_control(); self.assertIsNone(inputs.input_record(value))
        with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
            runner._flush_pending()
        self.assertEqual(numeric.call_count, 1); self.assertFalse(runner._PENDING)

    def test_retired_control_preserves_explicit_full_work(self):
        self.queue_scoped_work(full=True); self.retire_scoped_control()
        with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
            with patch.object(runner, 'run_dependency_runtime', wraps=runner.run_dependency_runtime) as run:
                runner._flush_pending()
        self.assertTrue(run.call_args.kwargs['full']); self.assertEqual(numeric.call_count, 1)

    def test_retired_control_only_keeps_explicit_nonfull_semantics(self):
        self.queue_scoped_work(full=False); self.retire_scoped_control()
        with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
            with patch.object(runner, 'run_dependency_runtime', wraps=runner.run_dependency_runtime) as run:
                runner._flush_pending()
        self.assertEqual(numeric.call_count, 0); self.assertFalse(runner._PENDING)
        if run.call_args: self.assertFalse(run.call_args.kwargs['full'])

    def test_retired_control_preserves_other_payload_and_intent(self):
        from anthroforge.core.deps import builtin_drivers, runtime_intents
        runtime_intents.enqueue_runtime_intent(self.root, 'OTHER/WORK', payload={'marker': 'intent'})
        self.queue_scoped_work(payload={'scp_recapture_ids': ['independent']}); self.retire_scoped_control()
        with patch.object(builtin_drivers, 'apply_runtime_intent', return_value={}) as apply:
            with patch.object(runner, 'run_dependency_runtime', wraps=runner.run_dependency_runtime) as run:
                runner._flush_pending()
        self.assertEqual(apply.call_args.args[2].payload, {'marker': 'intent'})
        self.assertEqual(run.call_args.kwargs['gate_meta']['payload']['scp_recapture_ids'], ['independent'])

    def test_retired_control_keeps_renamed_original_owners(self):
        self.queue_scoped_work({'MUSCLE': {self.muscle.id}}); self.retire_scoped_control()
        self.root.name = 'RenamedRoot'; self.scene.name = 'RenamedScene'
        with patch.object(runner, 'run_dependency_runtime') as run:
            runner._flush_pending()
        self.assertEqual(run.call_args.kwargs['root'], self.root)
        self.assertEqual(run.call_args.kwargs['scene'], self.scene)

    def test_retired_control_rejects_deleted_or_replaced_root(self):
        self.queue_scoped_work({'MUSCLE': {self.muscle.id}}, full=True); self.retire_scoped_control()
        name = self.root.name; bpy.data.objects.remove(self.root, do_unlink=True)
        replacement = bpy.data.objects.new(name, None); self.scene.collection.objects.link(replacement)
        with patch.object(runner, 'run_dependency_runtime') as run:
            runner._flush_pending()
        self.assertEqual(run.call_count, 0); self.assertFalse(runner._PENDING)

    def test_retired_control_rejects_deleted_or_replaced_scene(self):
        scene = bpy.data.scenes.new('OwnerScene')
        scene.collection.objects.link(self.root); scene.collection.objects.link(self.ctrl)
        self.scene = scene; self.queue_scoped_work({'MUSCLE': {self.muscle.id}}, full=True)
        inputs.retire_control(self.ctrl); name = scene.name; bpy.data.scenes.remove(scene)
        replacement = bpy.data.scenes.new(name); replacement.collection.objects.link(self.root)
        with patch.object(runner, 'run_dependency_runtime') as run:
            runner._flush_pending()
        self.assertEqual(run.call_count, 0); self.assertFalse(runner._PENDING)

    def test_tail_retired_control_preserves_independent_work(self):
        self.queue_scoped_work({'MUSCLE': {self.muscle.id}})
        item = runner._PENDING.pop(); ctx, request = runner._resolve_item(item)
        with patch.object(runner, '_RUNNING', True): runner._dispatch_runtime(ctx, request)
        self.retire_scoped_control()
        with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
            runner._run_one_request(*runner._pop_tail())
        self.assertEqual(numeric.call_count, 1)

    def test_tail_control_rejects_replaced_owner_before_execution(self):
        self.queue_scoped_work({'MUSCLE': {self.muscle.id}})
        ctx, request = runner._resolve_item(runner._PENDING.pop())
        with patch.object(runner, '_RUNNING', True): runner._dispatch_runtime(ctx, request)
        name = self.root.name; bpy.data.objects.remove(self.root, do_unlink=True)
        replacement = bpy.data.objects.new(name, None); self.scene.collection.objects.link(replacement)
        with patch.object(runner, 'run_dependency_runtime') as run:
            runner._run_one_request(*runner._pop_tail())
        self.assertEqual(run.call_count, 0)

    def test_deferred_control_payloads_do_not_coalesce_distinct_inputs(self):
        self.queue_scoped_work({'MUSCLE': {self.muscle.id}}, source='depsgraph', event_type='SCP_UPDATE')
        self.queue_scoped_work({'MUSCLE': {self.muscle.id}}, source='depsgraph', event_type='SCP_UPDATE')
        self.assertEqual(len(runner._PENDING), 2)

    def test_retired_control_keeps_independent_failed_request_for_retry(self):
        self.queue_scoped_work({'MUSCLE': {self.muscle.id}}); self.retire_scoped_control()
        self.assert_independent_failure_retry()

    def test_independent_failure_policy_without_control_envelope(self):
        runner.schedule_sync_from_dirty_hints(self.root, self.scene, {'MUSCLE': {self.muscle.id}}, full=False)
        self.assert_independent_failure_retry()

    def assert_independent_failure_retry(self):
        with patch.object(runner, 'run_dependency_runtime', side_effect=RuntimeError('independent failure')):
            with self.assertRaises(RuntimeError): runner._flush_pending()
        self.assertEqual(len(runner._PENDING), 1)
        with patch.object(module, 'execute_muscle_work', wraps=module.execute_muscle_work) as numeric:
            runner._flush_pending()
        self.assertEqual(numeric.call_count, 1); self.assertFalse(runner._PENDING)

    def test_invalid_original_owner_cannot_enter_either_queue(self):
        self.queue_scoped_work({'MUSCLE': {self.muscle.id}})
        ctx, request = runner._resolve_item(runner._PENDING.pop())
        bpy.data.objects.remove(self.root, do_unlink=True)
        self.assertIsNone(runner._enqueue_item(ctx, request))
        runner._enqueue_tail(ctx, request)
        self.assertFalse(runner._PENDING); self.assertFalse(runner._TAIL_PENDING)
