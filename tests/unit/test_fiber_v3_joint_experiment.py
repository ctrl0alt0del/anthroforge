import unittest

import numpy as np

from core.vcp.v3_experiment import clear_v3_experiment_caches, solve_v3_corridor
from core.vcp.v3_joint_experiment import solve_v3_joint
from tests.unit.test_fiber_v3_experiment import _request


class FiberV3JointExperimentTests(unittest.TestCase):
    def setUp(self):
        clear_v3_experiment_caches()

    def test_joint_result_is_finite_and_independently_valid(self):
        result = solve_v3_joint(_request(24, 24))
        self.assertTrue(result.valid)
        self.assertTrue(np.isfinite(np.asarray(result.points)).all())

    def test_joint_result_preserves_every_hard_pin(self):
        request = _request(24, 24); prior = solve_v3_corridor(request)
        result = solve_v3_joint(request, first_pass=prior)
        pins = np.asarray(result.corridor.pin_indices, dtype=np.int64)
        self.assertTrue(np.allclose(np.asarray(result.points)[pins], np.asarray(prior.points)[pins]))

    def test_joint_result_does_not_regress_structural_objective(self):
        request = _request(24, 24); prior = solve_v3_corridor(request)
        result = solve_v3_joint(request, first_pass=prior)
        self.assertLessEqual(result.objective, prior.objective + 1.0e-9)


if __name__ == "__main__":
    unittest.main()
