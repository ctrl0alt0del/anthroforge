import ast
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from core.vcp.v2 import (V2Termination, build_triangle_snapshot, solve_package5,
                         solve_package51, solve_package6, solve_package61,
                         solve_structural, validate_static_clearance)
import core.vcp.v2.solver_p61 as p61
from tests.unit.test_fiber_v2_planner import _angle_points, _anchors, _box, _request, _sphere


def _box_request():
    return _request(_anchors(((-1, 0, 0), (1, 0, 0))), (_box(),), 24, 0.05)


def _sphere_request():
    points = _angle_points((0.0, 0.12, 0.24, 0.36))
    return _request(_anchors(points, "SPHERE"), (_sphere(),), 64, 0.02)


def _bent_request():
    return _request(_anchors(((0, 0, 0), (.4, .5, 0), (1, 0, 0))), count=32)


def _clearance(result, request):
    return validate_static_clearance(result.result.points, build_triangle_snapshot(request.colliders),
        request.collision_policy.collision_radius, result.planner.contacts,
        slack=request.tolerances.clearance_slack)


class FiberV2AcceptedSolverTests(unittest.TestCase):
    def test_package61_light_workload_preserves_package51_fast_path(self):
        request = _bent_request(); expected = solve_package51(request); result = solve_package61(request)
        self.assertEqual(result.trace.selected_mode, "P51")
        self.assertEqual(result.result.points, expected.result.points)

    def test_package61_dynamic_path_is_safe_and_deterministic(self):
        request = _box_request()
        with _force_dynamic_dispatch():
            first, second = solve_package61(request), solve_package61(request)
        self.assertTrue(first.result.validated and _clearance(first, request).valid)
        self.assertEqual(first.result.points, second.result.points)

    def test_package6_is_deterministic_and_safe(self):
        request = _box_request(); first, second = solve_package6(request), solve_package6(request)
        self.assertEqual(first.result.points, second.result.points)
        self.assertTrue(first.result.validated and _clearance(first, request).valid)

    def test_package51_uses_one_final_static_validation(self):
        result = solve_package51(_sphere_request())
        self.assertTrue(result.result.validated)
        self.assertEqual(result.trace.static_validations, 1)

    def test_clear_reference_matches_structural_solution(self):
        request = _request(_anchors(((0, 0, 0), (1, .2, 0))), count=17)
        result = solve_package5(request)
        expected = solve_structural(result.planner.reference,
                                    {0: (0, 0, 0), 16: (1, .2, 0)}, request.settings)
        np.testing.assert_allclose(result.result.points, expected.points, atol=2.0e-12)

    def test_contact_projection_keeps_clearance(self):
        request = _box_request(); result = solve_package5(request)
        self.assertEqual(result.result.termination, V2Termination.BLOCKED)
        self.assertTrue(result.result.validated and _clearance(result, request).valid)

    def test_package5_is_deterministic(self):
        request = _box_request(); first, second = solve_package5(request), solve_package5(request)
        self.assertEqual(first.result.points, second.result.points)
        self.assertEqual(first.trace.active_counts, second.trace.active_counts)

    def test_solver_module_has_no_blender_dependency(self):
        path = Path(__file__).parents[2] / "core" / "vcp" / "v2" / "solver.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [name.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                 for name in node.names]
        self.assertNotIn("bpy", names)


def _force_dynamic_dispatch():
    rows = (patch.object(p61, "MINIMUM_PAIRS", 0),
            patch.object(p61, "MINIMUM_DENSITY", 0.0),
            patch.object(p61, "MINIMUM_EXCLUSION", 0.0),
            patch.object(p61, "MINIMUM_COMPRESSION", 0.0))
    return _PatchGroup(rows)


class _PatchGroup:
    def __init__(self, patches): self.patches = patches
    def __enter__(self):
        for value in self.patches: value.start()
    def __exit__(self, *args):
        for value in reversed(self.patches): value.stop()


if __name__ == "__main__":
    unittest.main()
