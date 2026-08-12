import unittest

from core.vcp.fiber_surface import FiberSurfaceSpec, evaluate_fiber_surface


class FiberSurfaceTests(unittest.TestCase):
    def test_loft_matches_expected_grid(self):
        rows = [[(0, 0, 0), (1, 0, 0)], [(0, 1, 0), (1, 1, 0)]]
        result = evaluate_fiber_surface(rows, FiberSurfaceSpec())
        self.assertEqual((len(result.vertices), result.faces), (4, ((0, 2, 3, 1),)))

    def test_loft_rejects_mismatched_rows(self):
        rows = [[(0, 0, 0), (1, 0, 0)], [(0, 1, 0)]]
        with self.assertRaisesRegex(ValueError, "same node count"):
            evaluate_fiber_surface(rows, FiberSurfaceSpec())

    def test_loft_flip_preserves_legacy_face_start(self):
        rows = [[(0, 0, 0), (1, 0, 0)], [(0, 1, 0), (1, 1, 0)]]
        result = evaluate_fiber_surface(rows, FiberSurfaceSpec(flip_normals=True))
        self.assertEqual(result.faces, ((0, 1, 3, 2),))

    def test_loop_patch_preserves_boundary(self):
        loop = [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]
        result = evaluate_fiber_surface([loop], FiberSurfaceSpec("LOOP_PATCH", patch_resolution=2))
        self.assertEqual(tuple(result.vertices[-4:]), tuple(loop))
        self.assertEqual((len(result.vertices), len(result.faces)), (9, 8))

    def test_loop_patch_rejects_self_intersection(self):
        loop = [(-1, -1, 0), (1, 1, 0), (-1, 1, 0), (1, -1, 0)]
        with self.assertRaisesRegex(ValueError, "self-intersects|degenerate"):
            evaluate_fiber_surface([loop], FiberSurfaceSpec("LOOP_PATCH"))

    def test_loop_patch_triangulates_concave_boundary(self):
        loop = [(0, 0, 0), (2, 0, 0), (2, 2, 0), (1, 1, 0), (0, 2, 0)]
        result = evaluate_fiber_surface([loop], FiberSurfaceSpec("LOOP_PATCH", patch_resolution=2))
        self.assertEqual(result.vertices[-len(loop):], tuple(loop))
        self.assertEqual(len(result.faces), 12)


if __name__ == "__main__":
    unittest.main()
