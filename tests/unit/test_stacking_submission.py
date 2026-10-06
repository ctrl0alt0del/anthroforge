"""Malformed public ABI requests must preserve the last completed result."""
import ctypes as C
import unittest
from core.muscle_pairs import abi as pairs
from core.muscle_pairs.model import DetectionSettings
from core.muscle_stacking import abi
from core.muscle_stacking.native import NativeStackEngine
from pair_fixture_adapter import wait
from test_muscle_stacking import inflated


class SubmissionTests(unittest.TestCase):
    def test_invalid_legacy_settings_keep_completed_result(self):
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
            self.assertEqual(status, 1)
            self.assertEqual(engine.summary()['generation'], before)
