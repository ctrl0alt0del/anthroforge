import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from core.vcp.v2 import (
    V2Anchor, V2AnchorRole, V2ColliderSnapshot, V2CollisionPolicy,
    V2PlannerBranch, V2PlannerMode, V2Quality, V2Request, V2ResolvedTolerances, V2Settings,
    V2Termination, V2Topology, build_triangle_snapshot, plan_reference,
    plan_reference_v41, plan_reference_v42, validate_static_clearance,
    plan_reference_v43,
)
from core.vcp.v2.collision import V2SegmentBatch
from core.vcp.v2.planner import validate_native_owner_chords
from core.vcp.v2 import solver_v23 as v23


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


def _scaled_sphere(scale):
    source = _sphere()
    points = tuple(tuple(float(scale) * value for value in point) for point in source.vertices)
    return V2ColliderSnapshot(source.collider_id, source.owner_id, points, source.triangles)


class _OwnerBlindWorld:
    def validate(self, points, edges, owners, span, threshold):
        _ = points, owners, span, threshold
        return V2SegmentBatch((True,) * len(edges), 0, 0, blockers=("",) * len(edges))

    def nearest(self, points):
        values = np.asarray(points, dtype=np.float64); count = len(values)
        return values, np.zeros_like(values), np.zeros(count), ("SPHERE",) * count, np.ones(count, bool)


class FiberV2PlannerTests(unittest.TestCase):
    def test_chord_guard_repairs_wide_direct_surface_handoff(self):
        collider = _scaled_sphere(5.4); points = _angle_points((0.0, .31, .62, .93))
        scaled = tuple(tuple(5.4 * value for value in point) for point in points)
        request = _request(_anchors(scaled, "SPHERE"), (collider,), 64, .002)
        snapshot = build_triangle_snapshot((collider,)); fixed = plan_reference_v43(request, snapshot, 8.0)
        checked = validate_static_clearance(fixed.reference, snapshot, .002, fixed.contacts, slack=.00002)
        self.assertEqual((fixed.termination, fixed.mode, len(fixed.reference)),
                         (V2Termination.CONVERGED, V2PlannerMode.SURFACE, 64))
        self.assertTrue(checked.valid)

    def test_owner_chord_guard_rejects_contained_clear_edge(self):
        collider = _scaled_sphere(5.4); points = _angle_points((0.0, .31))
        rows = tuple(tuple(5.4 * value for value in point) for point in points)
        request = _request(_anchors(rows, "SPHERE"), (collider,), 16, .002)
        result = validate_native_owner_chords(request, _OwnerBlindWorld(), np.asarray(rows), ((0, 1),),
                                              (("SPHERE", "SPHERE"),), .016, .00198)
        self.assertEqual(result.clear, (False,))
        self.assertEqual(v23._wide_direct_policy(request, _OwnerBlindWorld()), (False, True))

    def test_direct_reference_has_exact_count_and_pins(self):
        result = plan_reference(_request(_anchors(((0, 0, 0), (1, 0, 0))), count=17))
        self.assertEqual((result.termination, result.mode),
                         (V2Termination.CONVERGED, V2PlannerMode.DIRECT))
        self.assertEqual((len(result.reference), result.pin_indices), (17, (0, 16)))
        self.assertEqual((result.spans[0].branch, result.spans[0].edge_count),
                         (V2PlannerBranch.DIRECT, 16))

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

    def test_surface_bridge_metadata_matches_exact_count_spans(self):
        collider = _sphere(); points = _angle_points((0.0, 0.12, 0.24, 0.36))
        result = plan_reference_v43(_request(_anchors(points, "SPHERE"), (collider,), 64, 0.02))
        self.assertEqual({row.branch for row in result.spans},
                         {V2PlannerBranch.SURFACE_BRIDGE})
        self.assertEqual(sum(row.edge_count for row in result.spans), 63)
        self.assertEqual(tuple(row.first_edge for row in result.spans), result.pin_indices[:-1])
        self.assertEqual(tuple((row.start_anchor, row.end_anchor) for row in result.spans),
                         ((0, 1), (1, 2), (2, 3)))

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

    def test_v42_grouped_surface_chain_is_safe_and_deterministic(self):
        collider = _sphere(); points = _angle_points((0.0, 0.12, 0.24, 0.36))
        request = _request(_anchors(points, "SPHERE"), (collider,), 64, 0.02)
        first, second = plan_reference_v42(request), plan_reference_v42(request)
        checked = validate_static_clearance(first.reference, build_triangle_snapshot((collider,)),
                                            0.02, first.contacts, slack=0.0002)
        self.assertEqual((first.termination, first.reference), (V2Termination.CONVERGED, second.reference))
        self.assertTrue(checked.valid); self.assertEqual(first.diagnostics.chain_groups, 1)

    def test_v42_unrelated_obstacle_preserves_v41_result(self):
        request = _request(_anchors(((-1, 0, 0), (1, 0, 0))), (_box(),), 24, 0.05)
        old, new = plan_reference_v41(request), plan_reference_v42(request)
        self.assertEqual((old.termination, old.mode, old.reference),
                         (new.termination, new.mode, new.reference))

    def test_v43_matches_v41_direct_and_roadmap(self):
        requests = (_request(_anchors(((0, 0, 0), (1, 0, 0))), count=17),
                    _request(_anchors(((-1, 0, 0), (1, 0, 0))), (_box(),), 24, 0.05))
        for request in requests:
            old, new = plan_reference_v41(request), plan_reference_v43(request)
            self.assertEqual((old.termination, old.mode, old.reference, old.pin_indices),
                             (new.termination, new.mode, new.reference, new.pin_indices))

    def test_v43_surface_projection_is_deterministic_and_safe(self):
        collider = _sphere(); points = _angle_points((0, .12, .24, .36))
        request = _request(_anchors(points, "SPHERE"), (collider,), 64, .02)
        first, second = plan_reference_v43(request), plan_reference_v43(request)
        checked = validate_static_clearance(first.reference, build_triangle_snapshot((collider,)),
                                            .02, first.contacts, slack=.0002)
        self.assertEqual((first.termination, first.mode, first.reference),
                         (V2Termination.CONVERGED, V2PlannerMode.SURFACE, second.reference))
        self.assertTrue(checked.valid)

    def test_v43_rejects_unrelated_hard_anchor_before_graph_search(self):
        request = _request(_anchors(((0, 0, 0), (1, 0, 0)), "OWNER"), (_box(),), 16, 0.05)
        result = plan_reference_v43(request)
        self.assertEqual(result.termination, V2Termination.INVALID_ATTACHMENT)
        self.assertEqual(result.diagnostics.graph_searches, 0)
        self.assertIn("anchor 0", result.message)

    def test_v43_native_search_is_deterministic_and_independently_safe(self):
        collider = _box(); request = _request(_anchors(((-1, 0, 0), (1, 0, 0))), (collider,), 24, 0.05)
        first, second = plan_reference_v43(request), plan_reference_v43(request)
        checked = validate_static_clearance(first.reference, build_triangle_snapshot((collider,)),
                                            0.05, first.contacts, slack=0.0005)
        self.assertEqual((first.reference, first.corridor), (second.reference, second.corridor))
        self.assertTrue(checked.valid); self.assertGreater(first.diagnostics.native_collision_ms, 0.0)


if __name__ == "__main__":
    unittest.main()
