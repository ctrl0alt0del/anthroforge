import unittest
from pathlib import Path

import numpy as np

from core.vcp.v3.native_sqp_experiment import (EXPERIMENT_DLL, INDEXED_CCD, LEGACY_CCD,
                                                solve_native_sqp)
from core.vcp.v3.production import solve_v3
from tests.unit.test_fiber_v3_production import _bent_request


@unittest.skipUnless(Path(EXPERIMENT_DLL).exists(), "native SQP experiment DLL is not built")
class FiberV3NativeSqpExperimentTests(unittest.TestCase):
    def test_controller_matches_clear_production_result(self):
        request = _bent_request(20); expected = solve_v3(request, use_planner=False)
        actual = solve_native_sqp(request, INDEXED_CCD, use_planner=False)
        np.testing.assert_allclose(actual.points, expected.result.points, atol=3.0e-14, rtol=0.0)
        self.assertTrue(actual.validated)

    def test_legacy_and_indexed_ccd_are_exact_without_pairs(self):
        request = _bent_request(20)
        legacy = solve_native_sqp(request, LEGACY_CCD, use_planner=False)
        indexed = solve_native_sqp(request, INDEXED_CCD, use_planner=False)
        np.testing.assert_array_equal(legacy.points, indexed.points)
        self.assertEqual(legacy.spans[0].trajectory, indexed.spans[0].trajectory)

    def test_trajectory_records_native_controller_decisions(self):
        report = solve_native_sqp(_bent_request(20), INDEXED_CCD, use_planner=False)
        trials = sum(span.trials for span in report.spans)
        rows = sum((span.trajectory for span in report.spans), ())
        self.assertEqual(len(rows), trials)
        self.assertTrue(all(row[1] in {"ACCEPT", "REJECT", "INJECT", "CCD_REJECT"} for row in rows))


if __name__ == "__main__":
    unittest.main()
