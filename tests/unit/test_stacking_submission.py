"""Malformed public ABI requests must preserve the last completed result."""
import ctypes as C
import unittest
from core.muscle_pairs import abi as pairs
from core.muscle_pairs.model import DetectionSettings
from core.muscle_stacking import abi
from core.muscle_stacking.native import NativeStackEngine
from pair_fixture_adapter import wait
from test_muscle_stacking import inflated
from unittest.mock import patch
from core.muscle_stacking import vector


class SubmissionTests(unittest.TestCase):
    def test_vector_requires_constraint_declaration_for_every_domain(self):
        domains = [inflated('under', 0, .3), inflated('cover', .1, .2)]
        with NativeStackEngine() as engine:
            engine.submit(domains, DetectionSettings(), 1); before = wait(engine)
            with patch.object(vector, 'exact_arrays', return_value=((vector.Exact*0)(), [])):
                with self.assertRaisesRegex(ValueError, 'STACK_SUBMISSION_INVALID'):
                    engine.submit(domains, DetectionSettings(), 2)
            self.assertEqual(engine.summary(), before)

    def test_vector_malformed_constraint_batch_is_atomic(self):
        domains = [inflated('under', 0, .3), inflated('cover', .1, .2)]
        original = vector.exact_arrays
        def malformed(engine, values):
            exact, owned = original(engine, values)
            exact[0].width = 5
            return exact, owned
        with NativeStackEngine() as engine:
            engine.submit(domains, DetectionSettings(), 1); before = wait(engine)
            with patch.object(vector, 'exact_arrays', malformed):
                with self.assertRaisesRegex(ValueError, 'STACK_SUBMISSION_INVALID'):
                    engine.submit(domains, DetectionSettings(), 2)
            self.assertEqual(engine.summary(), before)

    def test_legacy_submission_is_retired_and_keeps_completed_result(self):
        domains = [inflated('under', 0, .3), inflated('cover', .1, .2)]
        with NativeStackEngine() as engine:
            engine.submit(domains, DetectionSettings(), 1); wait(engine)
            before = engine.summary()['generation']
            inputs = (pairs.Input*2)(*(engine._input(d) for d in domains))
            material = (abi.Material*2)(*(engine._material(d) for d in domains))
            detection = pairs.Settings(.05, 1e-14, 1e-10, 2000000, 4, 268435456, 268435456)
            invalid = abi.Settings(1, -1., .2, .8, .5)
            status = engine.library.af_stack_submit(engine.handle, inputs, 2, C.byref(detection),
                material, C.byref(invalid), None, 0, None, 0, 2)
            self.assertEqual(status, 4)
            engine.library.af_stack_legacy_diagnostic.restype = C.c_char_p
            self.assertIn(b'STACK_SCALAR_SUBMISSION_RETIRED', engine.library.af_stack_legacy_diagnostic())
            self.assertEqual(engine.summary()['generation'], before)
