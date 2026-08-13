import unittest
from unittest.mock import patch

import numpy as np

from core.vcp.fiber_ccd_reference import (
    ipc_environment_report,
    mesh_collision_free_step_reference,
    pilot_backend,
    pilot_swept_segment_triangle,
    segment_triangle_distance,
    swept_segment_triangle_reference,
)


TRIANGLE = np.array([[-1.0, -1.0, 0.0], [1.0, -1.0, 0.0], [0.0, 1.0, 0.0]])


def _vertical_motion(x=0.0):
    start = np.array([[x, 0.0, 1.0], [x + 0.1, 0.0, 1.0]])
    end = start.copy(); end[:, 2] = -1.0
    return start, end


def _horizontal_motion(height):
    start = np.array([[-2.0, 0.0, height], [-1.8, 0.0, height]])
    return start, start + np.array([4.0, 0.0, 0.0])


class FiberCcdPrimitiveTests(unittest.TestCase):
    def test_face_crossing_is_bounded(self):
        start, end = _vertical_motion()
        result = swept_segment_triangle_reference(start, end, TRIANGLE, 0.1)
        self.assertTrue(result.possible_collision)
        self.assertTrue(result.initially_valid)
        self.assertLessEqual(result.safe_step, 0.45)
        self.assertGreaterEqual(result.clearance_at_safe_step, 0.1)

    def test_crossing_with_clear_end_is_not_missed(self):
        start, end = _vertical_motion()
        result = swept_segment_triangle_reference(start, end, TRIANGLE)
        self.assertEqual(result.reason, "POSSIBLE_COLLISION")
        self.assertLess(result.safe_step, 0.5)
        self.assertEqual(segment_triangle_distance(*end, TRIANGLE), 1.0)

    def test_initial_contact_is_not_labeled_safe(self):
        start = np.array([[0.0, 0.0, 0.1], [0.1, 0.0, 0.1]])
        result = swept_segment_triangle_reference(start, start + [0.0, 0.0, 1.0], TRIANGLE, 0.1)
        self.assertEqual(result.reason, "INVALID_START")
        self.assertFalse(result.initially_valid)
        self.assertEqual(result.safe_step, 0.0)

    def test_exact_graze_is_conservative(self):
        start, end = _horizontal_motion(0.1)
        result = swept_segment_triangle_reference(start, end, TRIANGLE, 0.1)
        self.assertTrue(result.possible_collision)
        self.assertLess(result.safe_step, 1.0)
        self.assertGreaterEqual(result.clearance_at_safe_step, 0.1)

    def test_parallel_near_miss_is_clear(self):
        start, end = _horizontal_motion(0.1001)
        result = swept_segment_triangle_reference(start, end, TRIANGLE, 0.1)
        self.assertFalse(result.possible_collision)
        self.assertEqual(result.safe_step, 1.0)

    def test_coplanar_crossing_is_detected(self):
        start = np.array([[-3.0, 0.0, 0.0], [-2.5, 0.0, 0.0]])
        end = start + np.array([6.0, 0.0, 0.0])
        result = swept_segment_triangle_reference(start, end, TRIANGLE)
        self.assertTrue(result.possible_collision)
        self.assertLess(result.safe_step, 0.34)

    def test_thin_triangle_crossing_is_detected(self):
        triangle = np.array([[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0e-12, 0.0]])
        start, end = _vertical_motion()
        result = swept_segment_triangle_reference(start, end, triangle)
        self.assertTrue(result.possible_collision)
        self.assertLess(result.safe_step, 0.5)

    def test_degenerate_triangle_crossing_is_detected(self):
        triangle = np.array([[-1.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        start, end = _vertical_motion()
        result = swept_segment_triangle_reference(start, end, triangle)
        self.assertTrue(result.possible_collision)
        self.assertLess(result.safe_step, 0.5)

    def test_static_separation_is_clear(self):
        start, _end = _vertical_motion(3.0)
        result = swept_segment_triangle_reference(start, start, TRIANGLE, 0.1)
        self.assertFalse(result.possible_collision)
        self.assertEqual(result.safe_step, 1.0)

    def test_budget_exhaustion_is_not_clear(self):
        start, end = _vertical_motion()
        result = swept_segment_triangle_reference(start, end, TRIANGLE, max_intervals=1)
        self.assertEqual(result.reason, "BUDGET_EXHAUSTED")
        self.assertTrue(result.possible_collision)
        self.assertLess(result.safe_step, 1.0)

    def test_nonfinite_input_is_rejected(self):
        start, end = _vertical_motion()
        start[0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "finite"):
            swept_segment_triangle_reference(start, end, TRIANGLE)


class FiberCcdMeshTests(unittest.TestCase):
    def test_mesh_sweep_finds_earliest_pair(self):
        start, end = _vertical_motion()
        edges = np.array([[0, 1]])
        result = mesh_collision_free_step_reference(start, end, edges, TRIANGLE, [[0, 1, 2]], 0.1)
        self.assertTrue(result.possible_collision)
        self.assertTrue(result.initially_valid)
        self.assertLessEqual(result.safe_step, 0.45)
        self.assertEqual(result.tested_pairs, 1)

    def test_pair_filter_can_localize_owner_contact(self):
        start, end = _vertical_motion()
        edges = np.array([[0, 1]])
        result = mesh_collision_free_step_reference(start, end, edges, TRIANGLE, [[0, 1, 2]], 0.1,
                                                      pair_filter=lambda _edge, _face: False)
        self.assertFalse(result.possible_collision)
        self.assertEqual(result.tested_pairs, 0)
        self.assertEqual(result.safe_step, 1.0)

    def test_pair_steps_compose_in_global_time(self):
        vertices, triangles = _two_plane_mesh(0.0, 0.5)
        start = np.array([[0.0, 0.0, 1.0], [0.1, 0.0, 1.0]])
        end = start.copy(); end[:, 2] = -1.0
        result = mesh_collision_free_step_reference(start, end, [[0, 1]], vertices, triangles, 0.1)
        self.assertTrue(result.possible_collision)
        self.assertLessEqual(result.safe_step, 0.2)
        self.assertGreater(result.safe_step, 0.19)


def _two_plane_mesh(first_z, second_z):
    vertices = np.vstack((_translated_triangle(first_z), _translated_triangle(second_z)))
    return vertices, np.array([[0, 1, 2], [3, 4, 5]])


def _translated_triangle(height):
    result = TRIANGLE.copy()
    result[:, 2] = float(height)
    return result


class FiberCcdReferenceOracleTests(unittest.TestCase):
    def test_dense_observed_contacts_have_no_clear_result(self):
        rng = np.random.default_rng(1949)
        observed = 0
        for _index in range(80):
            start, end = rng.uniform(-1.5, 1.5, (2, 2, 3))
            if segment_triangle_distance(*start, TRIANGLE) <= 1.0e-6:
                continue
            dense = min(segment_triangle_distance(*(start + t * (end - start)), TRIANGLE) for t in np.linspace(0.0, 1.0, 201))
            result = swept_segment_triangle_reference(start, end, TRIANGLE)
            if dense <= 1.0e-12:
                observed += 1
                self.assertTrue(result.possible_collision)
        self.assertGreater(observed, 0)

    def test_safe_prefix_meets_clearance(self):
        rng = np.random.default_rng(1950)
        for _index in range(40):
            start, end = rng.uniform(-2.0, 2.0, (2, 2, 3))
            result = swept_segment_triangle_reference(start, end, TRIANGLE, 0.02)
            if result.initially_valid:
                self.assertGreater(result.clearance_at_safe_step, 0.02)


class FiberCcdPilotGateTests(unittest.TestCase):
    def test_pilot_defaults_disabled(self):
        self.assertEqual(pilot_backend({}), "disabled")
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            pilot_swept_segment_triangle(*_vertical_motion(), TRIANGLE, environment={})

    def test_reference_backend_requires_explicit_flag(self):
        environment = {"ANTHROFORGE_FIBER_CCD_PILOT": "reference"}
        result = pilot_swept_segment_triangle(*_vertical_motion(), TRIANGLE, environment=environment)
        self.assertTrue(result.possible_collision)

    def test_ipc_backend_remains_unapproved(self):
        environment = {"ANTHROFORGE_FIBER_CCD_PILOT": "ipctk"}
        with self.assertRaisesRegex(RuntimeError, "not approved"):
            pilot_swept_segment_triangle(*_vertical_motion(), TRIANGLE, environment=environment)

    def test_environment_report_never_enables_production(self):
        report = ipc_environment_report({"ANTHROFORGE_FIBER_CCD_PILOT": "ipctk"})
        self.assertEqual(report.requested_backend, "ipctk")
        self.assertTrue(report.legal_review_required)
        self.assertFalse(report.production_eligible)


if __name__ == "__main__":
    unittest.main()
