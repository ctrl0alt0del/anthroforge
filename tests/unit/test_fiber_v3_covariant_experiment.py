import unittest

import numpy as np

from core.vcp.v3_covariant_experiment import solve_v3_covariant
from core.vcp.v3_experiment import clear_v3_experiment_caches, solve_v3_corridor
from tests.unit.test_fiber_v3_experiment import _request


class FiberV3CovariantExperimentTests(unittest.TestCase):
    def setUp(self):
        clear_v3_experiment_caches()

    def test_coupled_result_remains_inside_corridor_and_valid(self):
        result = solve_v3_covariant(_request(24, 24))
        direct = np.asarray(result.corridor.direct); roadmap = np.asarray(result.corridor.roadmap)
        rebuilt = direct + np.asarray(result.alpha)[:, None] * (roadmap - direct)
        self.assertTrue(result.valid)
        self.assertTrue(np.allclose(rebuilt, result.points, atol=1.0e-12))

    def test_coupled_step_does_not_regress_objective(self):
        request = _request(24, 24); baseline = solve_v3_corridor(request)
        result = solve_v3_covariant(request)
        self.assertTrue(result.valid)
        self.assertLessEqual(result.objective, baseline.objective + 1.0e-9)
        self.assertGreater(result.trace.direction_ms, 0.0)

    def test_matching_warm_geometry_is_deterministic(self):
        request = _request(24, 24); cold = solve_v3_covariant(request)
        warm = solve_v3_covariant(request, warm_points=cold.points,
                                  warm_signature=cold.corridor.signature)
        self.assertTrue(warm.valid and warm.trace.warm_start)
        self.assertTrue(np.allclose(warm.points, cold.points, atol=1.0e-9))


if __name__ == "__main__":
    unittest.main()
