import ast
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from core.vcp.v2 import (V2Termination, build_triangle_snapshot, solve_package5, solve_package51, solve_package6,
                         solve_package61, solve_package71, solve_package72,
                         solve_package8, solve_package81, solve_package82,
                         solve_structural, validate_static_clearance)
import core.vcp.v2.solver_p61 as p61
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
    def test_package82_clear_case_is_exact_and_cap_invariant(self):
        request = _bent_request(); short = replace(request, settings=replace(request.settings, max_accepted_steps=2))
        first, second = solve_package82(short), solve_package82(request)
        self.assertEqual(first.result.termination, V2Termination.CONVERGED)
        self.assertEqual(first.result.points, second.result.points)
        self.assertLess(first.result.diagnostics.stationarity_residual, 1.0e-9)

    def test_package82_is_safe_and_deterministic(self):
        request = _box_request(); first, second = solve_package82(request), solve_package82(request)
        self.assertEqual(first.result.points, second.result.points)
        self.assertEqual(first.result.termination, second.result.termination)
        self.assertTrue(first.result.validated); self.assertTrue(_clearance(first, request).valid)

    def test_package81_clear_case_is_exact_and_cap_invariant(self):
        request = _bent_request(); short = replace(request, settings=replace(request.settings, max_accepted_steps=2))
        first, second = solve_package81(short), solve_package81(request)
        self.assertEqual(first.result.termination, V2Termination.CONVERGED)
        self.assertEqual(first.result.points, second.result.points)
        self.assertLess(first.result.diagnostics.stationarity_residual, 1.0e-9)

    def test_package81_is_safe_and_deterministic(self):
        request = _box_request(); first, second = solve_package81(request), solve_package81(request)
        self.assertEqual(first.result.points, second.result.points)
        self.assertEqual(first.result.termination, second.result.termination)
        self.assertTrue(first.result.validated); self.assertTrue(_clearance(first, request).valid)

    def test_package8_clear_case_is_exact_and_cap_invariant(self):
        request = _bent_request(); short = replace(request, settings=replace(request.settings, max_accepted_steps=2))
        first, second = solve_package8(short), solve_package8(request)
        self.assertEqual(first.result.termination, V2Termination.CONVERGED)
        self.assertEqual(first.result.points, second.result.points)
        self.assertLess(first.result.diagnostics.stationarity_residual, 1.0e-9)

    def test_package8_frozen_local_energies_do_not_increase(self):
        result = solve_package8(_box_request()); values = result.trace.local_energies
        self.assertTrue(values); self.assertTrue(all(np.isfinite(value) for value in values))
        self.assertTrue(result.result.validated); self.assertTrue(_clearance(result, _box_request()).valid)

    def test_package8_is_deterministic(self):
        first, second = solve_package8(_box_request()), solve_package8(_box_request())
        self.assertEqual(first.result.points, second.result.points)
        self.assertEqual(first.result.termination, second.result.termination)
        self.assertEqual(first.trace.reference_signature, second.trace.reference_signature)

    def test_package72_acquires_deterministic_shape_reference(self):
        first, second = solve_package72(_bent_request()), solve_package72(_bent_request())
        self.assertGreater(first.trace.acquisition_accepted, 0)
        self.assertEqual(first.trace.reference_signature, second.trace.reference_signature)
        self.assertEqual(first.result.points, second.result.points)

    def test_package72_shared_accepted_budget_is_respected(self):
        request = replace(_box_request(), settings=replace(_box_request().settings, max_accepted_steps=5))
        result = solve_package72(request)
        self.assertLessEqual(result.result.diagnostics.accepted_steps, 5)
        self.assertLessEqual(result.trace.acquisition_accepted, 4)

    def test_package72_rejection_activates_bounded_recovery(self):
        result = solve_package72(_box_request())
        self.assertGreaterEqual(result.trace.recovery_activations, 1)
        self.assertIn("TRUST", result.trace.controller_history)
        self.assertNotEqual(result.result.termination, V2Termination.BLOCKED)

    def test_package72_accepted_ratios_meet_threshold(self):
        result = solve_package72(_box_request())
        finite = [value for value in result.trace.ratio_history if np.isfinite(value)]
        self.assertTrue(finite); self.assertTrue(all(value >= 0.10 for value in finite))

    def test_package72_output_is_independently_safe(self):
        request = _box_request(); result = solve_package72(request)
        self.assertTrue(result.result.validated); self.assertTrue(_clearance(result, request).valid)
        self.assertEqual(result.result.engine_version, "fiber-v2-solver-package7.2-1")

    def test_package71_clear_case_matches_fixed_reference_solution(self):
        request = _bent_request(); result = solve_package71(request)
        pins = {index: anchor.point for index, anchor in zip(result.planner.pin_indices, request.anchors)}
        expected = solve_structural(result.planner.reference, pins, request.settings)
        np.testing.assert_allclose(result.result.points, expected.points, atol=2.0e-12)
        self.assertGreater(result.result.diagnostics.structural_energy, 0.0)

    def test_package71_clear_result_is_cap_invariant(self):
        request = _bent_request(); short = replace(request, settings=replace(request.settings, max_accepted_steps=2))
        long = replace(request, settings=replace(request.settings, max_accepted_steps=20))
        first, second = solve_package71(short), solve_package71(long)
        self.assertEqual(first.result.termination, V2Termination.CONVERGED)
        self.assertEqual(first.result.points, second.result.points)

    def test_package71_trace_and_stationarity_use_fixed_reference(self):
        first, second = solve_package71(_bent_request()), solve_package71(_bent_request())
        self.assertTrue(first.trace.fixed_reference); self.assertEqual(first.trace.reference_signature, second.trace.reference_signature)
        self.assertLess(first.result.diagnostics.stationarity_residual, 1.0e-9)
        self.assertEqual(first.result.points, second.result.points)

    def test_package71_contact_output_remains_independently_safe(self):
        request = _box_request(); result = solve_package71(request)
        self.assertTrue(result.result.validated); self.assertTrue(_clearance(result, request).valid)
        self.assertEqual(result.result.engine_version, "fiber-v2-solver-package7.1-1")

    def test_package61_light_workload_preserves_package51_fast_path(self):
        request = _bent_request(); expected = solve_package51(request); result = solve_package61(request)
        self.assertEqual(result.trace.selected_mode, "P51")
        self.assertEqual(result.result.points, expected.result.points)
        self.assertEqual(result.result.termination, expected.result.termination)

    def test_package61_forced_dynamic_path_is_safe_and_deterministic(self):
        request = _box_request()
        with patch.object(p61, "MINIMUM_PAIRS", 0), patch.object(p61, "MINIMUM_DENSITY", 0.0), patch.object(p61, "MINIMUM_EXCLUSION", 0.0), patch.object(p61, "MINIMUM_COMPRESSION", 0.0):
            first, second = solve_package61(request), solve_package61(request)
        self.assertTrue(first.result.validated); self.assertTrue(_clearance(first, request).valid)
        self.assertEqual(first.result.points, second.result.points)
        self.assertTrue(first.trace.certificates_enabled); self.assertGreaterEqual(first.trace.dispatch_ms, 0.0)

    def test_package61_rule_trace_is_auditable(self):
        result = solve_package61(_box_request()); trace = result.trace
        self.assertGreaterEqual(trace.dispatch_candidates, 0); self.assertGreaterEqual(trace.dispatch_density, 0.0)
        self.assertGreaterEqual(trace.dispatch_exclusion_ratio, 0.0)
        self.assertIn(trace.selected_mode, {"P51", "P61_CERTIFICATES", "P61_TRUST"})

    def test_package6_is_deterministic_and_independently_safe(self):
        request = _box_request(); first, second = solve_package6(request), solve_package6(request)
        self.assertEqual(first.result.points, second.result.points)
        self.assertTrue(first.result.validated); self.assertTrue(_clearance(first, request).valid)
        self.assertEqual(first.trace.trust_radii, second.trace.trust_radii)

    def test_package6_uses_one_ccd_path_per_trial(self):
        result = solve_package6(_box_request())
        self.assertEqual(result.trace.curved_waypoints, 0)
        self.assertLessEqual(len(result.trace.ccd_fractions), result.trace.trials)

    def test_package6_clear_fixed_point_is_not_trust_dependent(self):
        request = _bent_request(); result = solve_package6(request); expected = solve_package5(request)
        self.assertEqual(result.result.termination, V2Termination.CONVERGED)
        np.testing.assert_allclose(result.result.points, expected.result.points, atol=2.0e-12)

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
