import ast
from dataclasses import replace
from pathlib import Path
import unittest

import numpy as np

from core.vcp.v2 import (V2Termination, build_triangle_snapshot, solve_package5, solve_package51,
                         solve_structural, validate_static_clearance)
from tests.unit.test_fiber_v2_planner import (_anchors, _box, _request, _sphere,
                                              _angle_points)


def _box_request():
    return _request(_anchors(((-1, 0, 0), (1, 0, 0))), (_box(),), 24, 0.05)


def _sphere_request():
    points = _angle_points((0.0, 0.12, 0.24, 0.36))
    return _request(_anchors(points, "SPHERE"), (_sphere(),), 64, 0.02)


def _bent_request():
    points = ((0, 0, 0), (.4, .5, 0), (1, 0, 0))
    return _request(_anchors(points), count=32)


def _clearance(result, request):
    return validate_static_clearance(result.result.points, build_triangle_snapshot(request.colliders),
                                     request.collision_policy.collision_radius,
                                     result.planner.contacts,
                                     slack=request.tolerances.clearance_slack)


class FiberV2Package5Tests(unittest.TestCase):
    def test_package51_runs_only_final_static_validation(self):
        result = solve_package51(_sphere_request())
        self.assertTrue(result.result.validated); self.assertEqual(result.trace.static_validations, 1)
        self.assertEqual(result.trace.curved_waypoints, 0)

    def test_clear_reference_reaches_exact_structural_solution(self):
        request = _request(_anchors(((0, 0, 0), (1, 0.2, 0))), count=17)
        result = solve_package5(request); expected = solve_structural(
            result.planner.reference, {0: (0, 0, 0), 16: (1, 0.2, 0)}, request.settings)
        self.assertTrue(result.succeeded)
        np.testing.assert_allclose(result.result.points, expected.points, atol=2.0e-12)

    def test_contact_projection_preserves_box_clearance(self):
        request = _box_request(); result = solve_package5(request)
        self.assertEqual(result.result.termination, V2Termination.BLOCKED)
        self.assertTrue(_clearance(result, request).valid)
        self.assertTrue(result.result.validated)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in result.trace.ccd_fractions))

    def test_contact_weight_candidates_remain_feasible(self):
        request = _sphere_request()
        rows = [solve_package5(request, contact_weight=value)
                for value in (10.0, 100.0, 1000.0)]
        self.assertTrue(all(row.result.validated for row in rows))
        self.assertEqual(len({row.result.points for row in rows}), 1)

    def test_accepted_merit_is_nonincreasing(self):
        values = solve_package5(_bent_request()).trace.accepted_merits
        self.assertTrue(values)
        self.assertTrue(all(second <= first for first, second in zip(values, values[1:])))

    def test_warm_and_cold_results_agree(self):
        request = _sphere_request(); cold = solve_package5(request)
        warm = solve_package5(replace(request, warm_seed=cold.result.points))
        self.assertEqual(cold.result.termination, warm.result.termination)
        np.testing.assert_allclose(warm.result.points, cold.result.points, atol=1.0e-12)

    def test_package5_is_deterministic(self):
        request = _box_request(); first, second = solve_package5(request), solve_package5(request)
        self.assertEqual(first.result.points, second.result.points)
        self.assertEqual(first.trace.active_counts, second.trace.active_counts)

    def test_converged_contact_stationarity_is_small(self):
        result = solve_package5(_bent_request())
        self.assertEqual(result.result.termination, V2Termination.CONVERGED)
        self.assertLess(result.result.diagnostics.stationarity_residual, 1.0e-5)
        self.assertEqual(result.result.diagnostics.accelerated_steps, 0)

    def test_solver_module_has_no_blender_dependency(self):
        path = Path(__file__).parents[2] / "core" / "vcp" / "v2" / "solver.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [name.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                 for name in node.names]
        self.assertNotIn("bpy", names)


if __name__ == "__main__":
    unittest.main()
