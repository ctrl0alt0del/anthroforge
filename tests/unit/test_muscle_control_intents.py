"""Exact observations, scoped identity and atomic control consumption."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support import install_fake_modules
install_fake_modules()
from core.deps import muscle_control_intents as inputs


class Control(dict):
    name = 'control'
    session_uid = 3
    location = (0., 0., 0.)


class MuscleControlInputTests(unittest.TestCase):
    def setUp(self):
        inputs.reset_control_inputs()
        self.obj = Control(af_muscle_ctrl_sync_location=(0., 0., 0.))
        self.root = NS(name='root', session_uid=2)
        self.scene = NS(session_uid=1, objects={'control': self.obj, 'root': self.root})
        self.binding = patch.object(inputs, 'control_binding', return_value=('M', 'FS', 'S', '', 'A', 'CTRL_POINT', 4))
        self.binding.start()

    def tearDown(self):
        self.binding.stop()
        inputs.reset_control_inputs()

    def reserve(self, point):
        self.obj.location = point
        return inputs.reserve_input(self.root, self.scene, self.obj)

    def test_exact_duplicates_and_a_b_a_are_distinct(self):
        self.assertIsNone(self.reserve((0., 0., 0.)))
        a = self.reserve((1., 0., 0.))
        self.assertIsNone(self.reserve(a.point))
        b = self.reserve((2., 0., 0.))
        again = self.reserve(a.point)
        self.assertEqual([a.revision, b.revision, again.revision], [1, 2, 3])

    def test_evaluated_identity_keeps_raw_incoming_coordinates(self):
        evaluated = NS(original=self.obj, location=(1., 2., 3.))
        value = inputs.reserve_input(self.root, self.scene, evaluated)
        self.assertEqual(value.point, (1., 2., 3.))
        self.assertEqual(tuple(self.obj.location), (0., 0., 0.))
        self.assertIs(inputs.input_record(value).control, self.obj)
        self.assertTrue(inputs.claim_input(value))

    def test_small_movements_are_not_fuzzy_duplicates(self):
        first = self.reserve((1e-12, 0., 0.))
        second = self.reserve((2e-12, 0., 0.))
        self.assertEqual((first.revision, second.revision), (1, 2))

    def test_claim_is_atomic_and_handled_cannot_execute_again(self):
        value = self.reserve((1., 0., 0.))
        self.assertTrue(inputs.claim_input(value))
        self.assertFalse(inputs.claim_input(value))
        inputs.finish_input(value, True)
        self.assertFalse(inputs.claim_input(value))

    def test_failure_retains_one_retry_and_newer_success_retires_it(self):
        a = self.reserve((1., 0., 0.))
        inputs.claim_input(a); inputs.finish_input(a, False)
        self.assertIs(inputs.input_record(a).failed, a)
        self.assertIsNone(self.reserve(a.point))
        b = self.reserve((2., 0., 0.))
        inputs.claim_input(b); inputs.finish_input(b, True)
        inputs.finish_input(a, False)
        self.assertIsNone(inputs.input_record(b).failed)
        self.assertFalse(inputs.claim_input(a))

    def test_epoch_and_explicit_retirement_invalidate(self):
        a = self.reserve((1., 0., 0.))
        inputs.reset_control_inputs()
        self.assertIsNone(inputs.input_record(a))
        b = self.reserve((2., 0., 0.))
        inputs.retire_control(self.obj)
        self.assertIsNone(inputs.input_record(b))

    def test_external_deletion_and_replacement_are_pruned(self):
        a = self.reserve((1., 0., 0.))
        self.scene.objects['control'] = Control(other=True)
        inputs.prune_inputs()
        self.assertIsNone(inputs.input_record(a))
        self.assertEqual(len(inputs._RECORDS), 0)

    def test_binding_change_retires_old_envelope(self):
        a = self.reserve((1., 0., 0.))
        with patch.object(inputs, 'control_binding', return_value=('M', 'FS', 'S', 'branch', 'B', 'CTRL_POINT', 5)):
            b = self.reserve((2., 0., 0.))
            self.assertIsNone(inputs.input_record(a))
            self.assertIsNotNone(inputs.input_record(b))
            self.assertEqual(len(inputs._RECORDS), 1)

    def test_nonfinite_input_does_not_reserve(self):
        for value in (float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                self.reserve((value, 0., 0.))
        self.assertEqual(inputs._RECORDS, {})

    def test_retired_lifetime_cannot_claim_or_finish_replacement(self):
        old = self.reserve((1., 0., 0.)); inputs.retire_control(self.obj)
        new = self.reserve(old.point)
        self.assertEqual(old.revision, new.revision)
        self.assertNotEqual(inputs.input_key(old), inputs.input_key(new))
        self.assertFalse(inputs.claim_input(old)); self.assertTrue(inputs.claim_input(new))
        inputs.finish_input(old, False)
        record = inputs.input_record(new)
        self.assertEqual(record.processing, new.revision); self.assertIsNone(record.failed)
        self.assertFalse(inputs._input_matches(record, old))

    def test_binding_roundtrip_keeps_old_lifetime_invalid(self):
        old = self.reserve((1., 0., 0.))
        with patch.object(inputs, 'control_binding', return_value=('M', 'FS', 'S', 'branch', 'B', 'CTRL_POINT', 5)):
            temporary = self.reserve((2., 0., 0.))
        new = self.reserve(old.point)
        self.assertIsNone(inputs.input_record(old)); self.assertIsNone(inputs.input_record(temporary))
        self.assertTrue(inputs.claim_input(new))
        self.assertNotEqual(inputs.input_key(old), inputs.input_key(new))

    def test_pruned_record_recreated_with_same_owners_stays_distinct(self):
        old = self.reserve((1., 0., 0.))
        with patch.object(inputs, 'control_binding', return_value=None):
            inputs.prune_inputs()
        new = self.reserve(old.point)
        self.assertIsNone(inputs.input_record(old)); self.assertTrue(inputs.claim_input(new))

    def test_acquisition_guard_releases_after_failure(self):
        with self.assertRaises(RuntimeError):
            with inputs.acquisition_guard():
                self.assertTrue(inputs.input_busy())
                raise RuntimeError('failed')
        self.assertFalse(inputs.input_busy())


if __name__ == '__main__':
    unittest.main()
