from dataclasses import replace
from pathlib import Path
import ast
import unittest

from core.vcp.v2 import (V2Termination, clear_v21_route_cache, solve_package61,
                         solve_v21, v21_route_cache_stats)
from tests.unit.test_fiber_v2_solver import (_bent_request, _box_request,
                                              _clearance)


class FiberV21Tests(unittest.TestCase):
    def setUp(self):
        clear_v21_route_cache()

    def test_planner_matches_package61_reference(self):
        request = _box_request(); expected = solve_package61(request); result = solve_v21(request)
        self.assertEqual(result.planner.reference, expected.planner.reference)
        self.assertEqual(result.planner.contacts, expected.planner.contacts)
        self.assertIn(result.trace.planner_full_runs, (1, 2))

    def test_wide_direct_preflight_uses_one_plan(self):
        result = solve_v21(_bent_request())
        self.assertEqual(result.trace.planner_full_runs, 1)
        self.assertEqual(result.result.route_branch, "DIRECT")

    def test_exact_request_reuses_validated_route(self):
        request = _bent_request(); solve_v21(request); result = solve_v21(request)
        self.assertTrue(result.trace.planner_reused); self.assertTrue(result.trace.exact_route_hit)
        self.assertEqual(result.trace.planner_full_runs, 0)
        self.assertEqual(v21_route_cache_stats()["entries"], 1)

    def test_property_edit_revalidates_prior_corridor(self):
        request = _box_request(); solve_v21(request)
        settings = replace(request.settings, curvature_weight=request.settings.curvature_weight * 1.1)
        result = solve_v21(replace(request, token=2, settings=settings))
        self.assertTrue(result.trace.planner_reused); self.assertFalse(result.trace.exact_route_hit)
        self.assertGreater(result.trace.reuse_validation_ms, 0.0); self.assertTrue(result.result.validated)

    def test_collider_generation_change_forces_full_plan(self):
        request = _box_request(); solve_v21(request); collider = request.colliders[0]
        changed = replace(collider, generation=collider.generation + ("changed",))
        result = solve_v21(replace(request, token=2, colliders=(changed,)))
        self.assertFalse(result.trace.planner_reused); self.assertGreater(result.trace.planner_full_runs, 0)

    def test_linear_probe_falls_back_without_losing_safety(self):
        request = _box_request(); result = solve_v21(request)
        self.assertGreater(result.trace.direct_probes, 0); self.assertGreater(result.trace.curved_recoveries, 0)
        self.assertTrue(result.result.validated); self.assertTrue(_clearance(result, request).valid)

    def test_clear_case_remains_deterministic(self):
        request = _bent_request(); first = solve_v21(request); clear_v21_route_cache(); second = solve_v21(request)
        self.assertEqual(first.result.termination, V2Termination.CONVERGED)
        self.assertEqual(first.result.points, second.result.points)

    def test_v21_has_no_blender_dependency(self):
        path = Path(__file__).parents[2] / "core" / "vcp" / "v2" / "solver_v21.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names]
        self.assertNotIn("bpy", names)


if __name__ == "__main__":
    unittest.main()
