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
