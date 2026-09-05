import unittest

import numpy as np

from core.vcp.fiber_ccd_native import candidate_pairs_native, mesh_collision_free_step_native, native_available, pair_collision_free_step_native, swept_segment_triangle_native
from core.vcp.fiber_ccd_reference import mesh_collision_free_step_reference, swept_segment_triangle_reference


@unittest.skipUnless(native_available(), "native Fiber CCD binary is not built")
class FiberCcdNativeTests(unittest.TestCase):
    def _compare(self, start, end, triangle, clearance=0.0):
        reference = swept_segment_triangle_reference(start, end, triangle, clearance)
        native = swept_segment_triangle_native(start, end, triangle, clearance)
        self.assertEqual((native.reason, native.initially_valid), (reference.reason, reference.initially_valid))
        self.assertAlmostEqual(native.safe_step, reference.safe_step, places=13)

    def test_crossing_matches_reference(self):
        triangle = np.array([[-2,-2,0],[2,-2,0],[0,2,0]], dtype=float)
        self._compare([[-1,0,1],[1,0,1]], [[-1,0,-1],[1,0,-1]], triangle, 0.01)

    def test_clear_motion_matches_reference(self):
        triangle = np.array([[-2,-2,0],[2,-2,0],[0,2,0]], dtype=float)
        self._compare([[-1,0,1],[1,0,1]], [[-1,0,2],[1,0,2]], triangle, 0.01)

    def test_invalid_start_matches_reference(self):
        triangle = np.array([[-2,-2,0],[2,-2,0],[0,2,0]], dtype=float)
        self._compare([[-1,0,0],[1,0,0]], [[-1,0,1],[1,0,1]], triangle)

    def test_randomized_results_match_reference(self):
        random = np.random.default_rng(42)
        triangle = np.array([[-1,-1,0],[1,-1,0],[0,1,0]], dtype=float)
        for _index in range(100):
            start, end = random.normal(size=(2,3)), random.normal(size=(2,3))
            self._compare(start, end, triangle, 0.002)

    def test_mesh_safe_step_matches_reference(self):
        start = np.array([[-1,0,1],[1,0,1]], dtype=float)
        end = np.array([[-1,0,-1],[1,0,-1]], dtype=float)
        vertices = np.array([[-2,-2,0],[2,-2,0],[0,2,0]], dtype=float)
        args = start, end, np.array([[0,1]]), vertices, np.array([[0,1,2]])
        reference = mesh_collision_free_step_reference(*args, clearance=0.01)
        native = mesh_collision_free_step_native(*args, clearance=0.01)
        self.assertEqual((native.reason, native.tested_pairs), (reference.reason, reference.tested_pairs))
        self.assertAlmostEqual(native.safe_step, reference.safe_step, places=13)

    def test_explicit_pair_batch_matches_mesh_result(self):
        start = np.array([[-1,0,1],[1,0,1]], dtype=float)
        end = np.array([[-1,0,-1],[1,0,-1]], dtype=float)
        vertices = np.array([[-2,-2,0],[2,-2,0],[0,2,0]], dtype=float)
        edges, triangles = np.array([[0,1]]), np.array([[0,1,2]])
        pairs = candidate_pairs_native(start, end, edges, vertices, triangles, 0.01)
        result = pair_collision_free_step_native(start[edges[pairs[:,0]]], end[edges[pairs[:,0]]], vertices[triangles[pairs[:,1]]], 0.01)
        self.assertEqual((result.reason, result.tested_pairs), ("POSSIBLE_COLLISION", 1))


if __name__ == "__main__":
    unittest.main()
