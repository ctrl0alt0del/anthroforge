"""Footprints are disposable; compact results survive ordinary cache budgets."""
from dataclasses import replace
import unittest
import numpy as np
from core.muscle_pairs.native import NativePairEngine
from core.muscle_stacking.native import NativeStackEngine
from core.muscle_pairs.model import DetectionSettings
from core.muscle_stacking.model import StackingSettings
from pair_fixture_adapter import domain, wait
from pair_fixtures import rectangle
from stack_fixture_adapter import payload


def separated_pairs(count=12, n=10):
    return [rectangle(str((i, j)), (i*5, i*5+2, 0, 2), j*.03, n=n)
            for i in range(count) for j in range(2)]


class CompactStorage(unittest.TestCase):
    def check_storage(self, engine, domains, settings):
        engine.submit(domains, settings, 1); first = wait(engine)
        pair = engine.footprint(0, 1)
        order = engine.order_footprint(0, 1) if isinstance(engine, NativeStackEngine) else None
        engine.submit(domains, settings, 2); second = wait(engine)
        self.assertEqual(second['timings']['computed'], 0)
        self.assertEqual(second['timings']['reused'], 12)
        self.assertGreater(first['timings']['footprint_logical_bytes'], settings.result_bytes)
        self.assertLessEqual(first['timings']['detection_peak_working_bytes'], settings.result_bytes)
        for k, value in pair.items(): np.testing.assert_array_equal(engine.footprint(0, 2)[k], value)
        if order is not None:
            self.assertEqual(second['timings']['ordering_computed'], 0)
            for k, value in order.items(): np.testing.assert_array_equal(engine.order_footprint(0, 2)[k], value)

    def test_aggregate_geometry_exceeds_budget_without_truncation(self):
        settings = DetectionSettings(workers=1, cache_bytes=16384, result_bytes=300000)
        with NativePairEngine() as engine:
            self.check_storage(engine, [domain(s) for s in separated_pairs()], settings)

    def test_order_cache_and_lazy_geometry(self):
        settings = DetectionSettings(workers=1, cache_bytes=16384, result_bytes=300000,
                                     stacking=StackingSettings(enabled=False))
        with NativeStackEngine() as engine:
            self.check_storage(engine, [payload(s) for s in separated_pairs()], settings)

    def test_export_matches_exhaustive_after_local_change(self):
        values = [domain(s) for s in separated_pairs(2, 4)]
        with NativePairEngine() as engine:
            engine.submit(values, DetectionSettings(), 1); wait(engine)
            values[0] = replace(values[0], own=values[0].own + [0, 0, .01])
            engine.submit(values, DetectionSettings(), 2); summary = wait(engine)
            raw = [engine.footprint(i, 2) for i in range(len(summary['pairs']))]
            engine.submit(values, DetectionSettings(), 3, True); exhaustive = wait(engine)
            for i, pair in enumerate(exhaustive['pairs']):
                if not pair['fragments']: continue
                previous = next(j for j, p in enumerate(summary['pairs']) if p['first'] == pair['first'] and p['second'] == pair['second'])
                for k, value in raw[previous].items(): np.testing.assert_array_equal(engine.footprint(i, 3)[k], value)
