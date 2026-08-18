import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from core.vcp.v2 import (V2PlannerBranch, V2PlannerSpan, build_triangle_snapshot,
                         solve_v24, solve_v25_branch2)
from core.vcp.v2 import solver_v25_branch2 as v25
from tests.unit.test_fiber_v2_planner import _anchors, _request, _sphere, _angle_points


class FiberV25Branch2Tests(unittest.TestCase):
    def test_branch2_policy_is_selected_and_validated(self):
        collider = _sphere(); points = _angle_points((0.0, 0.5, 1.0, 1.5))
        request = _request(_anchors(points, "SPHERE"), (collider,), 64, 0.02)
        package = solve_v25_branch2(request, build_triangle_snapshot((collider,)))
        self.assertTrue(package.result.validated)
        self.assertTrue(package.trace.branch2_active)
        self.assertEqual({row.branch for row in package.planner.spans},
                         {V2PlannerBranch.SURFACE_BRIDGE})

    def test_branch2_preserves_every_authored_pin(self):
        collider = _sphere(); points = _angle_points((0.0, 0.5, 1.0, 1.5))
        request = _request(_anchors(points, "SPHERE"), (collider,), 64, 0.02)
        package = solve_v25_branch2(request, build_triangle_snapshot((collider,)))
        output = np.asarray(package.result.points)
        actual = output[np.asarray(package.planner.pin_indices, dtype=np.int64)]
        self.assertTrue(np.array_equal(actual, np.asarray(points)))

    def test_direct_path_is_identical_to_v24(self):
        request = _request(_anchors(((0, 0, 0), (1, 0, 0))), count=17)
        old, new = solve_v24(request), solve_v25_branch2(request)
        self.assertEqual(old.result.points, new.result.points)
        self.assertFalse(new.trace.branch2_active)

    def test_mixed_route_mask_selects_only_branch2_nodes(self):
        spans = (V2PlannerSpan(0, 2, V2PlannerBranch.DIRECT),
                 V2PlannerSpan(2, 2, V2PlannerBranch.SURFACE_BRIDGE, "OWNER"),
                 V2PlannerSpan(4, 2, V2PlannerBranch.DIRECT))
        state = SimpleNamespace(points=np.zeros((7, 3)),
                                request=SimpleNamespace(settings=SimpleNamespace(topology="OPEN")))
        with patch.object(v25.p5, "_cyclic", return_value=False):
            mask = v25._branch2_mask(state, spans[1:2])
        self.assertEqual(tuple(np.flatnonzero(mask)), (2, 3, 4))

    def test_recovery_only_activates_for_persistent_sharp_turns(self):
        self.assertFalse(v25._needs_recovery((56.0, 28.0)))
        self.assertTrue(v25._needs_recovery((71.0, 10.0)))
        self.assertTrue(v25._needs_recovery((20.0, 36.0)))

    def test_turn_metric_reports_straight_polyline_as_zero(self):
        points = np.asarray(((0, 0, 0), (1, 0, 0), (2, 0, 0)), dtype=float)
        self.assertAlmostEqual(float(v25._turn_values(points)[0]), 0.0)


if __name__ == "__main__":
    unittest.main()
