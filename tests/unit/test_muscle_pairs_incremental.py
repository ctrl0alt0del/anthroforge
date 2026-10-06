from dataclasses import replace
import unittest
import numpy as np
from core.muscle_pairs.native import NativePairEngine
from core.muscle_pairs.model import DetectionSettings
from pair_fixture_adapter import domain, wait
from pair_fixtures import rectangle


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.engine = NativePairEngine(); self.addCleanup(self.engine.close); self.generation = 0
        self.values = [domain(rectangle('r')), domain(rectangle('p', height=.03)), domain(rectangle('far', height=10))]

    def run_job(self, values=None, settings=None):
        self.generation += 1
        self.engine.submit(self.values if values is None else values, settings or DetectionSettings(), self.generation)
        return wait(self.engine)

    def test_identical_and_local_edit(self):
        first = self.run_job(); second = self.run_job()
        self.assertEqual(second['timings']['computed'], 0); self.assertEqual(second['timings']['reused'], 1)
        self.values[0] = replace(self.values[0], own=self.values[0].own+[0, 0, .1])
        self.assertEqual(self.run_job()['timings']['computed'], 1)

    def test_content_wins_over_revision(self):
        self.run_job(); self.values[1] = replace(self.values[1], own=self.values[1].own+[0, 0, 9])
        result = self.run_job(); self.assertEqual(result['timings']['reused'], 0)

    def test_new_neighbor_and_removal(self):
        self.run_job(); v = self.values[2]
        self.values[2] = replace(v, base=v.base-[0, 0, 10], own=v.own-[0, 0, 10])
        self.assertEqual(self.run_job()['timings']['broad_pairs'], 3)
        self.assertEqual(self.run_job(self.values[:1])['timings']['eligible_pairs'], 0)
        self.assertEqual(self.run_job()['timings']['computed'], 3)

    def test_group_direction_topology_and_provenance_invalidate(self):
        self.run_job(); a = self.values[0]
        for changed in (replace(a, direction=-a.direction), replace(a, faces=a.faces[:, ::-1]),
                        replace(a, parts=a.parts+1), replace(a, sources=a.sources+2)):
            self.assertEqual(self.run_job([changed, self.values[1]])['timings']['computed'], 1)
        self.assertEqual(self.run_job([replace(a, group='p'), self.values[1]])['timings']['eligible_pairs'], 0)

    def test_settings_and_eviction_recompute_without_loss(self):
        self.run_job(); config = DetectionSettings(search_distance=.2, cache_bytes=0)
        a = self.run_job(settings=config); b = self.run_job(settings=config)
        self.assertEqual(a['timings']['fragments'], b['timings']['fragments'])
        self.assertEqual(b['timings']['computed'], 1); self.assertEqual(b['timings']['reused'], 0)

    def test_limits_never_publish_truncated(self):
        for config in (DetectionSettings(result_bytes=1), DetectionSettings(fragment_limit=1)):
            with self.assertRaisesRegex(ValueError, 'BUDGET'): self.run_job(settings=config)
            with self.assertRaises(RuntimeError): self.engine.summary()
        self.assertGreater(self.run_job()['timings']['fragments'], 0)

    def test_invalid_batch_preserves_previous_result(self):
        self.run_job(); original = self.engine.footprint(0, self.generation)['point_array'].copy()
        bad = replace(self.values[0], base=self.values[0].base*np.nan)
        with self.assertRaises(ValueError): self.engine.submit([bad], DetectionSettings(), 500)
        np.testing.assert_array_equal(self.engine.footprint(0, self.generation)['point_array'], original)

    def test_cancellation_and_stale_revision(self):
        self.engine.submit(self.values, DetectionSettings(), 100); self.engine.cancel()
        with self.assertRaises(ValueError): wait(self.engine)
        self.run_job()
        with self.assertRaises(ValueError): self.engine.footprint(0, 100)

    def test_submitted_arrays_are_owned(self):
        values = [replace(v, base=v.base.copy(), own=v.own.copy()) for v in self.values]
        self.engine.submit(values, DetectionSettings(), 100)
        values[0].base[:] = 999; values[0].own[:] = 999
        self.assertEqual(wait(self.engine)['timings']['detected_pairs'], 1)

    def test_zero_batch_removes_every_domain(self):
        self.run_job(); self.assertEqual(self.run_job([])['timings']['broad_pairs'], 0)
        self.assertEqual(self.run_job()['timings']['computed'], 1)
