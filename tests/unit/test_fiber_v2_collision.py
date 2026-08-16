import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

import core.vcp.v2.collision as v2_collision
from core.vcp.fiber_ccd_reference import segment_triangle_distance
from core.vcp.v2 import (
    EDGE_BATCH, PAIR_BATCH, V2ColliderSnapshot, V2CollisionReason,
    V2OwnerContact, build_triangle_snapshot, cached_triangle_snapshot,
    build_native_collision_world,
    clear_triangle_snapshot_cache, collision_backend_status,
    collision_free_step, point_triangle_distances, segment_triangle_distances,
    triangle_snapshot_cache_stats,
    validate_segment_clearance_batch, validate_static_clearance,
)


def _collider(vertices, triangles=((0, 1, 2),), owner="BODY", collider_id="C"):
    points = tuple(tuple(float(value) for value in row) for row in vertices)
    return V2ColliderSnapshot(collider_id, owner, points, tuple(triangles))


def _plane(z=0.0, owner="BODY", collider_id="C"):
    vertices = ((-2, -2, z), (2, -2, z), (0, 2, z))
    return _collider(vertices, owner=owner, collider_id=collider_id)


def _transform(points, matrix, offset):
    return np.asarray(points) @ np.asarray(matrix).T + np.asarray(offset)


def _dense_first_hit(start, end, triangle, clearance, samples=4001):
    times = np.linspace(0.0, 1.0, samples)
    for time in times:
        segment = start + time * (end - start)
        if segment_triangle_distance(*segment, triangle) <= clearance:
            return float(time)
    return None


class FiberV2CollisionTests(unittest.TestCase):
    def test_package51_pair_cache_reuses_exact_set_and_prioritizes_limiter(self):
        cache = v2_collision.V2SweepPairCache(); pairs = np.asarray(((0, 1), (1, 2)))
        self.assertIs(cache.resolve(("a",), lambda: pairs), pairs)
        self.assertIs(cache.resolve(("a",), lambda: None), pairs); cache.note((1, 2))
        ordered = cache.resolve(("b",), lambda: pairs.copy())
        self.assertEqual(tuple(ordered[0]), (1, 2)); self.assertEqual((cache.hits, cache.misses), (2, 2))

    def test_packaged_backend_is_available(self):
        status = collision_backend_status()
        self.assertTrue(status.available, status.message)
        self.assertEqual(status.version, "af_fiber_ccd-2.1023")

    def test_package5_nearest_query_returns_surface_normal(self):
        world = build_native_collision_world((_plane(),))
        closest, normals, distances, blockers, contained = world.nearest(((0, 0, 1),))
        np.testing.assert_allclose(closest, ((0, 0, 0),), atol=1.0e-12)
        np.testing.assert_allclose(normals, ((0, 0, 1),), atol=1.0e-12)
        self.assertEqual((distances[0], blockers[0], bool(contained[0])), (1.0, "C", False))

    def test_package51_fused_contact_query_returns_edge_factor(self):
        world = build_native_collision_world((_plane(),))
        points = np.asarray(((-1, 0, .1), (1, 0, .1)))
        result = world.contacts(points, ((0, 1),), (("", ""),), 0.0, 0.2)
        self.assertEqual(result.active, (True,)); self.assertEqual(result.blockers, ("C",))
        self.assertAlmostEqual(result.distances[0], .1, places=12)
        self.assertGreaterEqual(result.factors[0], 0.0); self.assertLessEqual(result.factors[0], 1.0)
        self.assertGreater(result.normals[0, 2], .99)

    def test_persistent_snapshot_cache_reuses_generation(self):
        clear_triangle_snapshot_cache(); colliders = (_plane(),)
        first = cached_triangle_snapshot(colliders, ("scene", 1))
        second = cached_triangle_snapshot(colliders, ("scene", 1))
        third = cached_triangle_snapshot(colliders, ("scene", 2))
        self.assertIs(first, second); self.assertIsNot(first, third)
        self.assertEqual(triangle_snapshot_cache_stats(), {"entries": 2, "hits": 1, "misses": 2})

    def test_missing_and_incompatible_library_fail_closed(self):
        missing = collision_backend_status("Z:/missing/af_fiber_ccd.dll")
        incompatible_path = Path(os.environ["SystemRoot"]) / "System32" / "kernel32.dll"
        incompatible = collision_backend_status(incompatible_path)
        self.assertFalse(missing.available); self.assertFalse(incompatible.available)
        result = validate_static_clearance(((0, 0, 1), (1, 0, 1)), build_triangle_snapshot((_plane(),)), 0.1,
                                           backend_path="Z:/missing/af_fiber_ccd.dll")
        self.assertEqual(result.reason, V2CollisionReason.BACKEND_UNAVAILABLE)

    def test_snapshot_is_world_array_immutable(self):
        snapshot = build_triangle_snapshot((_plane(owner="A"), _plane(1.0, "B", "D")))
        self.assertEqual(snapshot.source_count, 2)
        self.assertEqual(snapshot.face_owners, ("A", "B"))
        self.assertFalse(snapshot.vertices.flags.writeable)
        self.assertFalse(snapshot.triangles.flags.writeable)
        np.testing.assert_array_equal(snapshot.triangles[1], (3, 4, 5))

    def test_static_primitive_distances_match_independent_reference(self):
        random = np.random.default_rng(71)
        segments = random.normal(size=(100, 2, 3)); triangles = random.normal(size=(100, 3, 3))
        expected = [segment_triangle_distance(*segment, triangle)
                    for segment, triangle in zip(segments, triangles)]
        np.testing.assert_allclose(segment_triangle_distances(segments, triangles), expected, atol=2.0e-13)
        points = segments[:, 0]
        expected_points = [segment_triangle_distance(point, point, triangle)
                           for point, triangle in zip(points, triangles)]
        np.testing.assert_allclose(point_triangle_distances(points, triangles), expected_points, atol=2.0e-13)

    def test_static_validator_detects_edge_with_clear_nodes(self):
        points = ((-2, 0, 0.1), (2, 0, 0.1))
        result = validate_static_clearance(points, build_triangle_snapshot((_plane(),)), 0.2)
        self.assertFalse(result.valid)
        self.assertEqual(result.violating_nodes, ())
        self.assertEqual(result.violating_edges, (0,))
        self.assertAlmostEqual(result.edge_minimum, 0.1)

    def test_segment_batch_matches_individual_static_validation(self):
        points = np.asarray(((-2, 0, 0.1), (2, 0, 0.1), (-2, 0, 1), (2, 0, 1)))
        edges = ((0, 1), (2, 3)); snapshot = build_triangle_snapshot((_plane(),))
        batch = validate_segment_clearance_batch(points, edges, snapshot, 0.2)
        expected = tuple(validate_static_clearance(points[list(edge)], snapshot, 0.2).valid
                         for edge in edges)
        self.assertEqual(batch.clear, expected)

    def test_package43_fused_batch_matches_reference_validation(self):
        points = np.asarray(((-2, 0, 0.1), (2, 0, 0.1), (-2, 0, 1), (2, 0, 1)))
        edges = ((0, 1), (2, 3)); collider = _plane(); world = build_native_collision_world((collider,))
        fused = world.validate(points, edges, (("", ""),) * 2, 0.5, 0.2)
        reference = validate_segment_clearance_batch(points, edges, build_triangle_snapshot((collider,)), 0.2)
        self.assertEqual(fused.clear, reference.clear)
        self.assertEqual(fused.blockers, ("C", ""))

    def test_package43_transform_refit_matches_clean_world(self):
        collider = _plane(); moved = np.eye(4); moved[2, 3] = 1.0
        points, edges = np.asarray(((-1, 0, 1), (1, 0, 1))), ((0, 1),)
        refit = build_native_collision_world((collider,)); refit.update_transform(0, moved)
        clean = build_native_collision_world((collider,), (moved,))
        first = refit.validate(points, edges, (("", ""),), 0.1, 0.01)
        second = clean.validate(points, edges, (("", ""),), 0.1, 0.01)
        self.assertEqual((first.clear, first.blockers), (second.clear, second.blockers))

    def test_package43_fused_containment_matches_reference(self):
        vertices = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))
        faces = ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3))
        collider = _collider(vertices, faces); points = np.asarray(((0.1, 0.1, 0.1), (2, 2, 2)))
        fused = build_native_collision_world((collider,)).validate(points, ((0, 1),), (("", ""),), 0.1, 0.01)
        reference = validate_segment_clearance_batch(points, ((0, 1),), build_triangle_snapshot((collider,)), 0.01)
        self.assertEqual(fused.clear, reference.clear)

    def test_segment_batch_owner_trim_remains_local(self):
        points = np.asarray(((0, 0, 0), (0, 0, 1), (0, 0, 0)))
        edges = ((0, 1), (2, 1)); snapshot = build_triangle_snapshot((_plane(owner="OWNER"),))
        owners = (("OWNER", ""), ("OTHER", ""))
        result = validate_segment_clearance_batch(points, edges, snapshot, 0.05,
                                                  owners, contact_span=0.1)
        self.assertEqual(result.clear, (True, False))

    def test_segment_batch_reuses_solve_local_containment(self):
        vertices = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))
        faces = ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3))
        snapshot = build_triangle_snapshot((_collider(vertices, faces),))
        points, edges, cache = np.asarray(((0.1, 0.1, 0.1), (2, 2, 2))), ((0, 1),), {}
        with patch.object(v2_collision, "_inside_memberships",
                          wraps=v2_collision._inside_memberships) as memberships:
            validate_segment_clearance_batch(points, edges, snapshot, 0.01, containment_cache=cache)
            validate_segment_clearance_batch(points, edges, snapshot, 0.01, containment_cache=cache)
        self.assertEqual(memberships.call_count, 1)

    def test_local_owner_contact_does_not_remove_same_owner_obstacle(self):
        near = _plane(0.0, "RIBS", "near"); far = _plane(0.5, "RIBS", "far")
        contact = V2OwnerContact("RIBS", (0,), ((0, 0.0, 0.1),))
        points = ((0, 0, 0), (0, 0, 1))
        local = validate_static_clearance(points, build_triangle_snapshot((near,)), 0.05, (contact,))
        blocked = validate_static_clearance(points, build_triangle_snapshot((near, far)), 0.05, (contact,))
        self.assertTrue(local.valid)
        self.assertFalse(blocked.valid)
        self.assertEqual(blocked.violating_edges, (0,))

    def test_owner_contact_never_exempts_unrelated_collider(self):
        contact = V2OwnerContact("OWNER", (0,), ((0, 0.0, 0.2),))
        snapshot = build_triangle_snapshot((_plane(owner="OTHER"),))
        result = validate_static_clearance(((0, 0, 0), (0, 0, 1)), snapshot, 0.05, (contact,))
        self.assertFalse(result.valid)
        self.assertIn(0, result.violating_nodes)

    def test_closed_mesh_containment_rejects_deep_interior_nodes(self):
        vertices = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))
        faces = ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3))
        snapshot = build_triangle_snapshot((_collider(vertices, faces),))
        result = validate_static_clearance(((0.1, 0.1, 0.1), (0.2, 0.1, 0.1)), snapshot, 0.01)
        self.assertFalse(result.valid)
        self.assertEqual(result.contained_nodes, (0, 1))

    def test_closed_tetrahedron_containment_matches_analytic_reference(self):
        vertices = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))
        faces = ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3))
        snapshot = build_triangle_snapshot((_collider(vertices, faces),)); random = np.random.default_rng(91)
        for _index in range(100):
            point = random.uniform(-0.2, 1.2, 3); other = point + (1e-7, 0, 0)
            expected = bool(np.all(point > 0.0) and point.sum() < 1.0)
            result = validate_static_clearance((point, other), snapshot, 0.0)
            self.assertEqual(0 in result.contained_nodes, expected)

    def test_mirrored_closed_containment_is_equivalent(self):
        vertices = np.asarray(((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)), dtype=float)
        faces = ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3))
        matrix = np.diag((-1.0, 1.0, 1.0)); offset = (3, -2, 5)
        snapshot = build_triangle_snapshot((_collider(_transform(vertices, matrix, offset), faces),))
        inside = _transform(((0.1, 0.1, 0.1), (0.2, 0.1, 0.1)), matrix, offset)
        self.assertEqual(validate_static_clearance(inside, snapshot, 0.01).contained_nodes, (0, 1))

    def test_open_mesh_does_not_claim_solid_containment(self):
        snapshot = build_triangle_snapshot((_plane(),))
        result = validate_static_clearance(((0, 0, 1), (0, 0, 2)), snapshot, 0.01)
        self.assertTrue(result.valid)
        self.assertEqual(result.contained_nodes, ())

    def test_sweep_reports_invalid_start(self):
        snapshot = build_triangle_snapshot((_plane(),))
        result = collision_free_step(((-1, 0, 0), (1, 0, 0)),
                                     ((-1, 0, 1), (1, 0, 1)), snapshot, 0.01)
        self.assertFalse(result.initially_valid)
        self.assertEqual(result.reason, V2CollisionReason.INVALID_START)
        self.assertEqual(result.safe_step, 0.0)

    def test_sweep_stops_before_clear_end_tunnels_through_plane(self):
        snapshot = build_triangle_snapshot((_plane(),))
        start = np.array([[-1, 0, 1], [1, 0, 1]], dtype=float)
        end = np.array([[-1, 0, -1], [1, 0, -1]], dtype=float)
        result = collision_free_step(start, end, snapshot, 0.01)
        self.assertTrue(result.initially_valid); self.assertTrue(result.valid)
        self.assertEqual(result.reason, V2CollisionReason.COLLISION)
        self.assertLess(result.safe_step, 0.5)
        self.assertGreaterEqual(segment_triangle_distance(*(start + result.safe_step * (end - start)),
                                                           np.asarray(_plane().vertices)), 0.01)

    def test_interval_budget_exhaustion_fails_closed(self):
        snapshot = build_triangle_snapshot((_plane(),))
        start = np.asarray(((-1, 0, 1), (1, 0, 1)), dtype=float)
        end = np.asarray(((-1, 0, -1), (1, 0, -1)), dtype=float)
        result = collision_free_step(start, end, snapshot, 0.01, interval_budget=1)
        self.assertFalse(result.valid)
        self.assertTrue(result.initially_valid)
        self.assertEqual(result.reason, V2CollisionReason.CCD_UNCERTAIN)

    def test_thin_degenerate_and_coplanar_static_cases(self):
        triangles = np.asarray((((0, 0, 0), (1e-12, 0, 0), (0, 1e-12, 0)),
                                ((-1, 0, 0), (1, 0, 0), (0, 0, 0))), dtype=float)
        segments = np.asarray((((0, 0, 1), (0, 0, 2)), ((-2, 0, 0), (2, 0, 0))), dtype=float)
        distances = segment_triangle_distances(segments, triangles)
        self.assertAlmostEqual(distances[0], 1.0)
        self.assertAlmostEqual(distances[1], 0.0)

    def test_grazing_motion_is_conservatively_limited(self):
        snapshot = build_triangle_snapshot((_plane(),))
        start = np.asarray(((-0.5, 0, 0.02), (0.5, 0, 0.02)))
        end = np.asarray(((-0.5, 0, 0.009), (0.5, 0, 0.009)))
        result = collision_free_step(start, end, snapshot, 0.01)
        self.assertTrue(result.valid)
        self.assertLess(result.safe_step, 1.0)
        self.assertGreaterEqual(segment_triangle_distance(*(start + result.safe_step * (end - start)),
                                                           np.asarray(_plane().vertices)), 0.01)

    def test_native_ccd_has_zero_dense_sample_misses(self):
        random = np.random.default_rng(19); triangle = np.asarray(_plane().vertices)
        snapshot = build_triangle_snapshot((_plane(),)); checked = 0
        for _index in range(50):
            start = random.uniform((-1, -1, 0.1), (1, 1, 1.5), size=(2, 3))
            end = random.uniform((-1, -1, -1.5), (1, 1, -0.1), size=(2, 3))
            hit = _dense_first_hit(start, end, triangle, 0.002)
            result = collision_free_step(start, end, snapshot, 0.002)
            if hit is not None:
                checked += 1; self.assertLessEqual(result.safe_step, hit + 3.0e-4)
        self.assertGreater(checked, 40)

    def test_rigid_and_mirrored_world_transforms_are_equivalent(self):
        start = np.array([[-1, 0, 1], [1, 0, 1]], dtype=float)
        end = np.array([[-1, 0, -1], [1, 0, -1]], dtype=float)
        matrix = np.array([[0, -1, 0], [-1, 0, 0], [0, 0, 1]], dtype=float)
        offset = (4.0, -7.0, 2.5); triangle = np.asarray(_plane().vertices)
        base = collision_free_step(start, end, build_triangle_snapshot((_plane(),)), 0.01)
        moved = _collider(_transform(triangle, matrix, offset), owner="BODY")
        transformed = collision_free_step(_transform(start, matrix, offset), _transform(end, matrix, offset),
                                          build_triangle_snapshot((moved,)), 0.01)
        self.assertAlmostEqual(base.safe_step, transformed.safe_step, places=12)

    def test_native_batches_respect_declared_limits(self):
        x = np.linspace(-1.0, 1.0, 131)
        start = np.column_stack((x, np.zeros_like(x), np.ones_like(x)))
        end = start.copy(); end[:, 2] = -1.0
        result = collision_free_step(start, end, build_triangle_snapshot((_plane(),)), 0.01)
        self.assertGreater(result.candidate_pairs, 128)
        self.assertLessEqual(result.max_edge_batch, EDGE_BATCH)
        self.assertLessEqual(result.max_pair_batch, PAIR_BATCH)

    def test_collision_module_is_blender_and_v1_independent(self):
        path = Path(__file__).parents[2] / "core" / "vcp" / "v2" / "collision.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        names = [item.name for node in ast.walk(tree) if isinstance(node, ast.Import) for item in node.names]
        self.assertNotIn("bpy", names)
        self.assertFalse(any("fiber_ccd_" in str(module) for module in imports))


if __name__ == "__main__":
    unittest.main()
