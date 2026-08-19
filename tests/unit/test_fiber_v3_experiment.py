import unittest

import numpy as np

from core.vcp.v2 import (V2Anchor, V2AnchorRole, V2ColliderSnapshot, V2CollisionPolicy,
                         V2Quality, V2Request, V2ResolvedTolerances, V2Settings,
                         V2Topology, build_triangle_snapshot, validate_static_clearance)
from core.vcp.v3_experiment import clear_v3_experiment_caches, plan_v3_corridor, solve_v3_corridor


def _box():
    points = ((-.3, -.3, -.3), (.3, -.3, -.3), (.3, .3, -.3), (-.3, .3, -.3),
              (-.3, -.3, .3), (.3, -.3, .3), (.3, .3, .3), (-.3, .3, .3))
    faces = ((0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7))
    return V2ColliderSnapshot("BOX", "BLOCKER", points, faces)


def _request(count=12, steps=12):
    anchors = (V2Anchor((-1, 0, 0), "", V2AnchorRole.ENDPOINT_A, 0),
               V2Anchor((1, 0, 0), "", V2AnchorRole.ENDPOINT_B, 1))
    settings = V2Settings(V2Topology.OPEN, V2Quality.INTERACTIVE, count, steps, .9, .02, 1.0)
    tolerances = V2ResolvedTolerances(clearance_slack=.0005, length_scale=2.0)
    return V2Request(1, "scene", "root", "revision", settings, tolerances,
                     V2CollisionPolicy(.05), anchors, (_box(),))


class FiberV3ExperimentTests(unittest.TestCase):
    def setUp(self):
        clear_v3_experiment_caches()

    def test_planner_pairs_exact_direct_and_safe_roadmap(self):
        request = _request(); snapshot = build_triangle_snapshot(request.colliders)
        corridor = plan_v3_corridor(request, snapshot)
        checked = validate_static_clearance(corridor.roadmap, snapshot, .05,
                                            corridor.contacts, slack=.0005)
        self.assertTrue(corridor.succeeded and checked.valid)
        self.assertEqual((len(corridor.direct), len(corridor.roadmap), corridor.pin_indices), (12, 12, (0, 11)))

    def test_cold_solution_stays_in_corridor_and_is_valid(self):
        request = _request(); result = solve_v3_corridor(request)
        direct, roadmap = np.asarray(result.corridor.direct), np.asarray(result.corridor.roadmap)
        rebuilt = direct + np.asarray(result.alpha)[:, None] * (roadmap - direct)
        self.assertTrue(result.valid)
        self.assertTrue(np.allclose(rebuilt, result.points, atol=1e-12))
        self.assertLessEqual(result.length, np.linalg.norm(np.diff(roadmap, axis=0), axis=1).sum())

    def test_matching_warm_geometry_is_reused_deterministically(self):
        request = _request(12, 8); cold = solve_v3_corridor(request)
        warm = solve_v3_corridor(request, warm_points=cold.points,
                                 warm_signature=cold.corridor.signature, allow_exact_cache=False)
        self.assertTrue(warm.trace.warm_start and warm.valid)
        self.assertTrue(np.allclose(warm.points, cold.points, atol=1e-10))
        self.assertAlmostEqual(warm.objective, cold.objective, places=9)

    def test_exact_result_cache_revalidates_before_replay(self):
        request = _request(12, 8); cold = solve_v3_corridor(request)
        replay = solve_v3_corridor(request)
        self.assertTrue(replay.trace.exact_cache_hit and replay.valid)
        self.assertEqual(replay.points, cold.points)

    def test_planner_route_cache_is_reused(self):
        request = _request(); snapshot = build_triangle_snapshot(request.colliders)
        first = plan_v3_corridor(request, snapshot)
        second = plan_v3_corridor(request, snapshot)
        self.assertFalse(first.planner_reused)
        self.assertTrue(second.planner_reused and second.exact_route_hit)


if __name__ == "__main__":
    unittest.main()
