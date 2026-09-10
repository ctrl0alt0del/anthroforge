import unittest
from dataclasses import replace
from unittest.mock import patch

import numpy as np

from core.vcp.v2 import planner
from core.vcp.v2.planner_anchor_access import (
    anchor_access_candidates, append_access_neighbors, append_access_points, _exit_directions,
)
from tests.unit.test_fiber_v2_planner import _anchors, _box, _request


def _fixture():
    anchors = _anchors(((0, 0, .3), (0, 0, -.3)), "OWNER")
    request = _request(anchors, (_box(owner="OWNER"),), count=32, radius=.02)
    state = planner._v43_state(request, None, 2.5)
    corners = np.asarray(_box(half=.34).vertices)
    return state, (*[np.asarray(row.point) for row in anchors], *corners)


class FiberPlannerAnchorAccessTests(unittest.TestCase):
    def test_normal_exits_connect_isolated_pins_without_changing_clearance(self):
        state, candidates = _fixture(); start, end = state.request.anchors
        graph = planner._checked_anchor_neighbors(state, candidates, planner._neighbor_rows(np.asarray(candidates), True), start, end)
        self.assertIsNone(planner._search_batched_lazy(state, candidates, np.asarray(candidates), graph, "OWNER", "OWNER"))
        with patch.object(planner, "_roadmap_candidates", return_value=candidates):
            route = planner._anchor_access_route(state, start, end)
        self.assertIsNotNone(route)
        self.assertTrue(planner._route_clear(state, route, "OWNER", "OWNER"))
        result = planner._finish_plan(state, (planner._roadmap_segment(route),), 0.0)
        self.assertTrue(result.succeeded)
        self.assertEqual((len(result.reference), result.pin_indices), (32, (0, 31)))
        self.assertEqual((result.reference[0], result.reference[-1]), (start.point, end.point))
        self.assertEqual(state.owner_contact_factor, 2.5)

    def test_new_points_are_clear_without_owner_exemptions(self):
        state, _points = _fixture(); start, end = state.request.anchors
        points = anchor_access_candidates(state, start, end, planner._batch_edge_states)
        self.assertEqual(len(points), 4)
        edges = tuple((i, i) for i in range(len(points)))
        result = state.native_world.validate(points, edges, (), 0.0, .0198)
        self.assertTrue(all(result.clear))

    def test_unrelated_obstacle_rejects_normal_exits(self):
        state, _points = _fixture(); source = _box("OTHER", "OTHER", .1)
        blocker = replace(source, vertices=tuple(tuple(np.asarray(p) + (0, 0, .41)) for p in source.vertices))
        request = replace(state.request, colliders=(*state.request.colliders, blocker))
        state = planner._v43_state(request, None, 2.5); start, end = request.anchors
        points = anchor_access_candidates(state, start, end, planner._batch_edge_states)
        self.assertEqual(len(points), 2)
        self.assertTrue(all(point[2] < 0 for point in points))

    def test_missing_owner_does_not_generate_unbound_exits(self):
        state, _points = _fixture(); start, end = state.request.anchors
        empty = replace(start, owner_id="")
        points = anchor_access_candidates(state, empty, empty, planner._batch_edge_states)
        self.assertEqual(points, ())

    def test_oblique_exits_avoid_blocked_normal_without_moving_pin(self):
        state, _points = _fixture(); source = _box("OTHER", "OTHER", .002)
        blocker = replace(source, vertices=tuple(tuple(np.asarray(p) + (0, 0, .34)) for p in source.vertices))
        request = replace(state.request, colliders=(*state.request.colliders, blocker))
        state = planner._v43_state(request, None, 2.5); start, end = request.anchors
        normal = anchor_access_candidates(state, start, end, planner._batch_edge_states)
        oblique = anchor_access_candidates(state, start, end, planner._batch_edge_states, True)
        self.assertFalse(any(point[2] > .3 for point in normal))
        self.assertTrue(any(point[2] > .3 for point in oblique))
        self.assertEqual(start.point, (0, 0, .3))

    def test_reference_only_state_does_not_require_native_fallback(self):
        state, _points = _fixture(); state.native_world = None
        with patch("core.vcp.v2.planner.anchor_access_candidates") as generate:
            self.assertIsNone(planner._anchor_access_route(state, *state.request.anchors))
        generate.assert_not_called()

    def test_augmented_graph_preserves_old_edges(self):
        points = np.asarray(((0, 0, 0), (4, 0, 0), (2, 0, 0), (.001, 0, 0)))
        original = ((2,), (2,), (0, 1))
        graph = append_access_neighbors(points, original, limit=1)
        for index, row in enumerate(original): self.assertTrue(set(row).issubset(graph[index]))
        self.assertIn(3, graph[0]); self.assertIn(3, graph[1])
        self.assertEqual(graph, append_access_neighbors(points, original, limit=1))

    def test_existing_duplicate_vertices_keep_their_graph_indices(self):
        original = ((0, 0, 0), (1, 0, 0), (0, 0, 0))
        result = append_access_points(original, ((1, 0, 0), (2, 0, 0), (2, 0, 0)))
        self.assertEqual(result, (*original, (2, 0, 0)))

    def test_oblique_directions_are_bounded_finite_and_deterministic(self):
        for normal in np.eye(3):
            directions = _exit_directions(normal, True)
            self.assertEqual(len(directions), 10)
            np.testing.assert_allclose(np.linalg.norm(directions, axis=1), 1.0)
            np.testing.assert_array_equal(directions, _exit_directions(normal, True))

    def test_successful_roadmap_does_not_query_exits(self):
        state, candidates = _fixture(); route = candidates[:2]
        with patch.object(planner, "_roadmap_route_with", return_value=route):
            with patch.object(planner, "_anchor_access_route") as fallback:
                self.assertEqual(planner._roadmap_route_v41(state, *state.request.anchors), route)
        fallback.assert_not_called()


if __name__ == "__main__": unittest.main()
