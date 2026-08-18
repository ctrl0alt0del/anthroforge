import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from core.vcp.v2 import solve_pin_smoothing, solve_v24
from core.vcp.v2 import solver_pin_smoothing as smoothing
from core.vcp.v2.collision_native import native_batch_status
from tests.unit.test_fiber_v24 import _array_request


class _PlaneWorld:
    def nearest(self, points):
        values = np.asarray(points); closest = values.copy(); closest[:, 2] = 0.0
        normals = np.tile((0.0, 0.0, 1.0), (len(values), 1))
        distances = np.abs(values[:, 2]); ids = np.zeros(len(values), dtype=np.int64)
        return closest, normals, distances, ids, np.zeros(len(values), dtype=bool)


def _retraction_state():
    points = np.column_stack((np.arange(6.0), np.zeros(6), np.ones(6)))
    span = SimpleNamespace(first_edge=0, edge_count=5, branch=SimpleNamespace(value="SURFACE_BRIDGE"), owner_id="A")
    policy = SimpleNamespace(collision_radius=0.2); request = SimpleNamespace(collision_policy=policy)
    return SimpleNamespace(points=points, pins={0: points[0], 5: points[5]}, owner_worlds={"A": _PlaneWorld()},
                           request=request, nearest_ms=0.0), span


class FiberPinSmoothingSolverTests(unittest.TestCase):
    def test_recovery_only_replaces_first_partial_step(self):
        self.assertTrue(smoothing._should_recover(0, True, False))
        self.assertFalse(smoothing._should_recover(1, True, False))
        self.assertFalse(smoothing._should_recover(0, True, True))

    def test_cyclic_topology_is_not_modified(self):
        settings = SimpleNamespace(topology=smoothing.V2Topology.CYCLIC)
        live = SimpleNamespace(request=SimpleNamespace(settings=settings),
                               planner=SimpleNamespace(pin_indices=(0, 4)))
        self.assertFalse(smoothing._recoverable(live))

    def test_isolated_turn_does_not_activate_recovery(self):
        tail = tuple((i, 1, 0) for i in range(2, 100))
        points = np.asarray(((0, 0, 0), (1, 0, 0), (1, 1, 0), *tail))
        settings = SimpleNamespace(topology=smoothing.V2Topology.OPEN)
        live = SimpleNamespace(points=points, request=SimpleNamespace(settings=settings),
                               planner=SimpleNamespace(pin_indices=(0, len(points) - 1)))
        self.assertFalse(smoothing._recoverable(live))

    def test_dynamic_dispatch_delegates_to_v24_path(self):
        live = SimpleNamespace(certificates_enabled=True)
        expected = smoothing.V2Termination.BUDGET_EXHAUSTED, "dynamic"
        with patch.object(smoothing.v21, "_solve_state", return_value=expected) as solve:
            actual = smoothing._iterate_live(live)
        self.assertEqual(actual, (*expected, None)); solve.assert_called_once_with(live)

    def test_turn_acceptance_rejects_any_quality_regression(self):
        self.assertTrue(smoothing._turns_improve((40, 20, 100), (39, 19, 99)))
        self.assertFalse(smoothing._turns_improve((40, 20, 100), (39, 21, 99)))

    @unittest.skipUnless(native_batch_status(), "native V2.4 batch ABI is unavailable")
    def test_clear_direct_result_matches_v24(self):
        request = _array_request(); old = solve_v24(request); new = solve_pin_smoothing(request)
        self.assertEqual(new.result.points, old.result.points)
        self.assertTrue(new.result.validated); self.assertFalse(new.trace.smoothing_active)

    def test_tangent_projection_preserves_normal_offset(self):
        normal = np.asarray((0.0, 0.0, 1.0)); delta = np.asarray(((1.0, 2.0, 3.0),))
        projected = smoothing._tangent_rows(delta, normal)
        self.assertEqual(float(projected[0, 2]), 0.0)

    def test_bridge_candidate_retracts_only_free_span_nodes(self):
        state, span = _retraction_state(); result = smoothing._bridge_candidate(state, (span,), 2.0)
        np.testing.assert_array_equal(result[[0, 5]], state.points[[0, 5]])
        np.testing.assert_allclose(result[1:5, 2], 0.4)

    def test_bridge_selector_ignores_other_planner_branches(self):
        bridge = SimpleNamespace(branch=SimpleNamespace(value="SURFACE_BRIDGE"), owner_id="A")
        mesh = SimpleNamespace(branch=SimpleNamespace(value="SURFACE_MESH"), owner_id="A")
        self.assertEqual(smoothing._bridge_spans((mesh, bridge)), (bridge,))

    def test_retraction_requires_one_coherent_owner_corridor(self):
        row = lambda first, owner="A", lift=4: SimpleNamespace(first_edge=first, edge_count=2, owner_id=owner, lift_factor=lift)
        self.assertTrue(smoothing._retraction_supported((row(0), row(2))))
        self.assertFalse(smoothing._retraction_supported((row(0), row(3))))
        self.assertFalse(smoothing._retraction_supported((row(0), row(2), row(4))))
        self.assertFalse(smoothing._retraction_supported((row(0, lift=2.5),)))

    def test_roadmap_route_does_not_use_early_pin_recovery(self):
        settings = SimpleNamespace(topology=smoothing.V2Topology.OPEN)
        span = SimpleNamespace(branch=SimpleNamespace(value="ROADMAP"))
        points = np.asarray(((0, 0, 0), (1, 0, 0), (1, 1, 0)))
        planner = SimpleNamespace(pin_indices=(0, 2), spans=(span,))
        live = SimpleNamespace(request=SimpleNamespace(settings=settings), planner=planner, points=points)
        self.assertFalse(smoothing._recoverable(live))

    def test_surface_boundary_uses_the_surface_side_tangent(self):
        branch = lambda value: SimpleNamespace(value=value)
        surface = SimpleNamespace(first_edge=0, edge_count=3, branch=branch("SURFACE_BRIDGE"), owner_id="A")
        direct = SimpleNamespace(first_edge=3, edge_count=3, branch=branch("DIRECT"), owner_id="")
        request = SimpleNamespace(anchors=(None, SimpleNamespace(owner_id="A")))
        state = SimpleNamespace(request=request, planner=SimpleNamespace(spans=(surface, direct)))
        self.assertEqual(smoothing._surface_side(state, SimpleNamespace(pin=3, anchor=1)), "incoming")

    def test_surface_tangent_acceptance_requires_large_peak_reduction(self):
        self.assertTrue(smoothing._surface_turns_improve((90, 10, 200), (58, 11, 160)))
        self.assertFalse(smoothing._surface_turns_improve((90, 10, 200), (85, 9, 150)))

    def test_global_pin_recovery_requires_one_surface_bridge_owner(self):
        points = np.asarray(((0,0,0),(1,0,0),(2,0,0),(2,1,0),(2,2,0),(3,2,0),(4,2,0)), dtype=float)
        branch = SimpleNamespace(value="SURFACE_BRIDGE")
        spans = tuple(SimpleNamespace(branch=branch, owner_id="A") for _ in range(3))
        anchors = tuple(SimpleNamespace(owner_id="A") for _ in range(4))
        state = SimpleNamespace(points=points, pins={i: points[i] for i in (0,2,4,6)},
                                planner=SimpleNamespace(spans=spans), request=SimpleNamespace(anchors=anchors))
        self.assertTrue(smoothing._global_pin_supported(state))
        state.request.anchors = (*anchors[:-1], SimpleNamespace(owner_id="B"))
        self.assertFalse(smoothing._global_pin_supported(state))


if __name__ == "__main__":
    unittest.main()
