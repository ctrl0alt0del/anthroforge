import unittest

import numpy as np

from core.vcp.v3_experiment import clear_v3_experiment_caches, solve_v3_corridor
from core.vcp.v3_transverse_experiment import (_active_mask, _bounds, _frame,
                                                solve_v3_transverse)
from tests.unit.test_fiber_v3_experiment import _request


class FiberV3TransverseExperimentTests(unittest.TestCase):
    def setUp(self):
        clear_v3_experiment_caches(); self.request = _request(12, 8)
        self.first = solve_v3_corridor(self.request)

    def test_transport_frame_is_unit_and_orthogonal_to_tangent(self):
        frame = _frame(self.first); points = np.asarray(self.first.points)
        tangent = points[2:] - points[:-2]
        self.assertTrue(np.allclose(np.linalg.norm(frame, axis=1), 1.0))
        self.assertTrue(np.allclose(np.einsum("ij,ij->i", frame[1:-1], tangent), 0.0, atol=1e-9))

    def test_bounds_fix_pins_and_contain_first_pass(self):
        active = _active_mask(self.first.points, self.first.corridor.pin_indices, "full")
        low, high, _axes = _bounds(self.request, self.first, _frame(self.first), active)[0]
        pins = np.asarray(self.first.corridor.pin_indices)
        self.assertTrue(np.all(low <= 0.0) and np.all(high >= 0.0))
        self.assertTrue(np.all(low[pins] == 0.0) and np.all(high[pins] == 0.0))

    def test_full_pass_never_replaces_valid_result_with_worse_candidate(self):
        result = solve_v3_transverse(self.request, first_pass=self.first, mode="full")
        self.assertTrue(result.valid)
        self.assertLessEqual(result.length, 1.02 * self.first.length)
        if not result.accepted: self.assertEqual(result.points, self.first.points)

    def test_windowed_pass_uses_no_more_active_nodes_than_full(self):
        full = solve_v3_transverse(self.request, first_pass=self.first, mode="full")
        window = solve_v3_transverse(self.request, first_pass=self.first, mode="windowed")
        self.assertLessEqual(window.trace.active_nodes, full.trace.active_nodes)


if __name__ == "__main__":
    unittest.main()
