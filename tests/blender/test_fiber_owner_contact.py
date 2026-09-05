from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from mathutils import Vector

ADDON_ROOT = Path(__file__).resolve().parents[2]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from anthroforge.core.vcp.fiber_solver import FiberSolver
from anthroforge.core.vcp.fiber_planner import PlannerAnchor
from anthroforge.core.vcp.fiber_progressive import FiberSolveSession, _route_seed
from anthroforge.core.visualization import fiber_sync_runtime
from anthroforge.core.visualization import fiber_refinement


class _BandOracle:
    margin, clearance = 0.0, 0.1

    def __init__(self, half_width):
        self.half_width = float(half_width)
        self._colliders = ({"sid": "RIB"},)

    def active_colliders_for_polyline(self, points, padding=0.0):
        _ = points, padding
        return self._colliders

    def push_out_point(self, point, colliders):
        hit = bool(colliders) and abs(float(point.x)) < self.half_width
        return point.copy(), 1.0 if hit else 0.0


def _params(pin=2):
    return {"margin": 0.0, "segment_collisions": True, "eps_pen": 1.0e-5,
            "pin_owners": {pin: "RIB"}}


class FiberOwnerContactTests(unittest.TestCase):
    def test_deep_same_owner_traversal_is_not_masked(self):
        solver, oracle = FiberSolver(), _BandOracle(0.4)
        nodes = [Vector((x, 0.0, 0.0)) for x in (-1.0, -0.25, 0.0, 0.25, 1.0)]
        residual = solver._final_residual(nodes, oracle, _params())
        self.assertGreater(residual, 0.5)

    def test_authored_pin_contact_remains_legal_locally(self):
        solver, oracle = FiberSolver(), _BandOracle(0.05)
        nodes = [Vector((x, 0.0, 0.0)) for x in (-1.0, 0.0, 1.0)]
        residual = solver._final_residual(nodes, oracle, _params(1))
        self.assertEqual(residual, 0.0)

    def test_owner_permission_is_bounded_in_world_distance(self):
        solver, oracle = FiberSolver(), _BandOracle(0.4)
        nodes = [Vector((x, 0.0, 0.0)) for x in (-1.0, -0.25, 0.0, 0.25, 1.0)]
        zones = {"RIB": ((2, 2),)}
        interval = solver._owner_trim_interval(
            nodes, 2, 3, oracle, oracle._colliders[0], _params(), zones)
        self.assertIsNone(interval)

    def test_owner_zone_is_independent_of_collision_state(self):
        solver, oracle = FiberSolver(), _BandOracle(10.0)
        nodes = [Vector((float(i), 0.0, 0.0)) for i in range(5)]
        zones = solver._owner_zone_limits(nodes, oracle, oracle._colliders, _params())
        self.assertEqual(zones, {"RIB": ((2, 2),)})

    def test_planner_corners_survive_exact_count_expansion(self):
        solver = FiberSolver()
        route = [Vector((x, y, 0.0)) for x, y in ((0, 0), (1, 2), (2, 0), (3, 2), (4, 0))]
        expanded = solver._preserve_polyline(route, 17)
        self.assertTrue(all(any((point - node).length < 1.0e-9 for node in expanded)
                            for point in route))

    def test_roadmap_seed_wins_over_surface_guide(self):
        solver = FiberSolver()
        anchors = [PlannerAnchor(Vector((0, 0, 0))), PlannerAnchor(Vector((4, 0, 0)))]
        route = [Vector((x, y, 0.0)) for x, y in ((0, 0), (1, 2), (2, 0), (3, 2), (4, 0))]
        selected = solver._preferred_route_seed(anchors, [Vector((2, 3, 0))], route)
        self.assertEqual([tuple(point) for point in selected], [tuple(point) for point in route])

    def test_progressive_roadmap_seed_wins_over_surface_guide(self):
        route = [Vector((x, y, 0.0)) for x, y in ((0, 0), (1, 2), (2, 0))]
        session = FiberSolveSession(FiberSolver(), None, object(), None, None)
        session.anchors = [PlannerAnchor(route[0]), PlannerAnchor(route[-1])]
        session.preview, session.guides, session.mode = route, [Vector((1, 3, 0))], "ROADMAP"
        self.assertEqual([tuple(point) for point in _route_seed(session)], [tuple(point) for point in route])

    def test_unsafe_mid_touch_output_is_not_committable(self):
        fiber = type("Fiber", (), {"node_count": 3, "solver_version": 1,
                     "use_segment_collisions": False, "mid_touches": (object(),),
                     "loop_anchors": (), "get": lambda *_args: 0})()
        points = [Vector((float(index), 0.0, 0.0)) for index in range(3)]
        with patch.object(fiber_sync_runtime, "fiber_eps_pen", return_value=0.5), \
             patch.object(fiber_sync_runtime, "fiber_invalid_reason", return_value=""):
            self.assertFalse(fiber_sync_runtime._sync_commit_allowed(fiber, points))

    def test_progressive_v1_requires_safe_final_residual(self):
        fiber = type("Fiber", (), {"solver_version": 1, "use_segment_collisions": True})()
        self.assertFalse(fiber_refinement._result_safe(
            fiber, type("Result", (), {"converged": False, "max_pen": 0.5})()))

    def test_v2_commit_uses_resolved_native_validation(self):
        fiber = type("Fiber", (), {})()
        result = type("Result", (), {"engine": "V2", "validated": True, "max_pen": 2.0e-5})()
        self.assertTrue(fiber_refinement._result_safe(fiber, result))

if __name__ == "__main__":
    unittest.main()
