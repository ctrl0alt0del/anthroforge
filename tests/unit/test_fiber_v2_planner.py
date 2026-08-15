import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from core.vcp.v2 import (
    V2Anchor, V2AnchorRole, V2ColliderSnapshot, V2CollisionPolicy,
    V2PlannerMode, V2Quality, V2Request, V2ResolvedTolerances, V2Settings,
    V2Termination, V2Topology, build_triangle_snapshot, plan_reference,
    plan_reference_v41, validate_static_clearance,
)


def _anchors(points, owner=""):
    roles = [V2AnchorRole.TOUCH] * len(points)
    roles[0], roles[-1] = V2AnchorRole.ENDPOINT_A, V2AnchorRole.ENDPOINT_B
    return tuple(V2Anchor(point, owner, roles[index], index) for index, point in enumerate(points))


def _request(anchors, colliders=(), count=32, radius=0.02, topology=V2Topology.OPEN):
    settings = V2Settings(topology=topology, quality=V2Quality.INTERACTIVE, node_count=count)
    tolerances = V2ResolvedTolerances(clearance_slack=max(1.0e-9, radius * 0.01))
    policy = V2CollisionPolicy(collision_radius=radius)
    return V2Request(1, "scene", "root", "revision", settings, tolerances,
                     policy, tuple(anchors), tuple(colliders))


def _box(identifier="BOX", owner="BLOCKER", half=0.3):
    h = float(half)
    points = ((-h, -h, -h), (h, -h, -h), (h, h, -h), (-h, h, -h),
              (-h, -h, h), (h, -h, h), (h, h, h), (-h, h, h))
    faces = ((0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
             (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
             (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7))
    return V2ColliderSnapshot(identifier, owner, points, faces)


def _sphere(segments=24, rings=12):
    points = [(0.0, 0.0, 1.0)]
    _sphere_points(points, segments, rings)
    points.append((0.0, 0.0, -1.0))
    return V2ColliderSnapshot("SPHERE", "SPHERE", points,
                              _sphere_faces(segments, rings, len(points) - 1))


def _sphere_points(points, segments, rings):
    for ring in range(1, rings):
        angle = np.pi * ring / rings
        for segment in range(segments):
            longitude = 2.0 * np.pi * segment / segments
            points.append((np.sin(angle) * np.cos(longitude),
                           np.sin(angle) * np.sin(longitude), np.cos(angle)))


def _sphere_faces(segments, rings, bottom):
    faces = [(0, 1 + index, 1 + (index + 1) % segments) for index in range(segments)]
    _sphere_bands(faces, segments, rings)
    start = 1 + (rings - 2) * segments
    faces.extend((start + index, bottom, start + (index + 1) % segments)
                 for index in range(segments))
    return tuple(faces)


def _sphere_bands(faces, segments, rings):
    for ring in range(rings - 2):
        first, second = 1 + ring * segments, 1 + (ring + 1) * segments
        for index in range(segments):
            nxt = (index + 1) % segments
            faces.extend(((first + index, second + index, second + nxt),
                          (first + index, second + nxt, first + nxt)))


def _angle_points(values):
    return tuple((np.cos(value), np.sin(value), 0.0) for value in values)


class FiberV2PlannerTests(unittest.TestCase):
    def test_direct_reference_has_exact_count_and_pins(self):
        result = plan_reference(_request(_anchors(((0, 0, 0), (1, 0, 0))), count=17))
        self.assertEqual((result.termination, result.mode),
                         (V2Termination.CONVERGED, V2PlannerMode.DIRECT))
        self.assertEqual((len(result.reference), result.pin_indices), (17, (0, 16)))

    def test_unrelated_box_uses_safe_roadmap_and_preserves_corners(self):
        collider = _box(); request = _request(_anchors(((-1, 0, 0), (1, 0, 0))), (collider,), 16, 0.05)
        result = plan_reference(request); snapshot = build_triangle_snapshot((collider,))
        validation = validate_static_clearance(result.reference, snapshot, 0.05,
                                               result.contacts, slack=0.0005)
        self.assertEqual((result.mode, len(result.reference), validation.valid),
                         (V2PlannerMode.ROADMAP, 16, True))
        self.assertTrue(all(any(np.allclose(point, corner) for point in result.reference)
                            for corner in result.corridor))

    def test_surface_route_avoids_sphere_fanning(self):
        collider = _sphere(); points = _angle_points((0.0, 0.12, 0.24, 0.36))
        result = plan_reference(_request(_anchors(points, "SPHERE"), (collider,), 64, 0.02))
        angles = np.unwrap(np.arctan2(np.asarray(result.reference)[:, 1],
                                     np.asarray(result.reference)[:, 0]))
        self.assertEqual((result.mode, len(result.reference)), (V2PlannerMode.SURFACE, 64))
        self.assertTrue(np.all(np.diff(angles) >= -1.0e-9))
        self.assertLess(float(np.ptp(angles)), 0.5)

    def test_result_is_deterministic(self):
        request = _request(_anchors(((-1, 0, 0), (1, 0, 0))), (_box(),), 24, 0.05)
        first, second = plan_reference(request), plan_reference(request)
        self.assertEqual((first.reference, first.corridor, first.pin_indices),
                         (second.reference, second.corridor, second.pin_indices))

    def test_inside_start_reports_no_feasible_path(self):
        request = _request(_anchors(((0, 0, 0), (1, 0, 0))), (_box(),), 16, 0.05)
        result = plan_reference(request)
        self.assertEqual(result.termination, V2Termination.NO_FEASIBLE_PATH)

    def test_cyclic_reference_has_exact_count_and_pin_order(self):
        points = ((1, 0, 0), (-0.5, 0.8, 0), (-0.5, -0.8, 0))
        result = plan_reference(_request(_anchors(points), count=18, topology=V2Topology.CYCLIC))
        self.assertEqual((len(result.reference), len(result.pin_indices)), (18, 3))
        self.assertEqual(tuple(result.reference[index] for index in result.pin_indices), points)

    def test_missing_backend_fails_closed(self):
        request = _request(_anchors(((0, 0, 0), (1, 0, 0))))
        with patch("core.vcp.v2.planner.collision_backend_status",
                   return_value=SimpleNamespace(available=False)):
            result = plan_reference(request, build_triangle_snapshot(()))
        self.assertEqual(result.termination, V2Termination.BACKEND_UNAVAILABLE)

    def test_simple_roadmap_stays_within_interactive_budget(self):
        request = _request(_anchors(((-1, 0, 0), (1, 0, 0))), (_box(),), 16, 0.05)
        started = time.perf_counter(); plan_reference(request)
        self.assertLess(1000.0 * (time.perf_counter() - started), 150.0)

    def test_v41_matches_package4_reference(self):
        requests = (_request(_anchors(((0, 0, 0), (1, 0, 0))), count=17),
                    _request(_anchors(((-1, 0, 0), (1, 0, 0))), (_box(),), 24, 0.05),
                    _request(_anchors(_angle_points((0, .12, .24, .36)), "SPHERE"), (_sphere(),), 64, .02))
        for request in requests:
            old, new = plan_reference(request), plan_reference_v41(request)
            self.assertEqual((old.termination, old.mode, old.reference, old.pin_indices),
                             (new.termination, new.mode, new.reference, new.pin_indices))

    def test_v41_reuses_graph_metric_without_extra_collision_edges(self):
        request = _request(_anchors(((-1, 0, 0), (1, 0, 0))), (_box(),), 16, 0.05)
        old, new = plan_reference(request), plan_reference_v41(request)
        self.assertEqual(new.diagnostics.graph_searches, old.diagnostics.graph_searches)
        self.assertEqual(new.diagnostics.tested_edges, old.diagnostics.tested_edges)
        self.assertEqual(new.diagnostics.frontier_edges, 0)
        self.assertEqual(new.diagnostics.graph_metric_builds, 1)

    def test_v41_is_deterministic_and_independently_valid(self):
        collider = _box(); request = _request(_anchors(((-1, 0, 0), (1, 0, 0))), (collider,), 24, 0.05)
        first, second = plan_reference_v41(request), plan_reference_v41(request)
        result = validate_static_clearance(first.reference, build_triangle_snapshot((collider,)),
                                           0.05, first.contacts, slack=0.0005)
        self.assertEqual((first.reference, first.corridor), (second.reference, second.corridor))
        self.assertTrue(result.valid)


if __name__ == "__main__":
    unittest.main()
