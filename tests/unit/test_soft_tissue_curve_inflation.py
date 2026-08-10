import unittest

from core.vcp.soft_tissue_curve_inflation import (
    CurveRidgeProfile,
    backing_vertex_indices,
    commissure_vertex_indices,
    geometric_curve_relaxation,
    inflate_curve_ridge,
)


class SoftTissueCurveInflationTests(unittest.TestCase):
    def setUp(self):
        self.points = ((-1.0, 0.0, 0.0), (0.0, 0.2, 0.0), (1.0, 0.0, 0.0))
        self.normals = ((0.0, 0.0, 1.0),) * 3
        self.profile = CurveRidgeProfile(profile_segments=5, endpoint_taper=0.25)

    def test_curve_inflates_into_closed_host_sealed_ridge(self):
        mesh = inflate_curve_ridge(self.points, self.normals, self.profile)
        self.assertEqual((len(mesh.vertices), len(mesh.faces), mesh.ring_size), (15, 12, 5))
        self.assertTrue(all(len(face) >= 4 for face in mesh.faces))

    def test_profile_boundaries_remain_on_host_surface(self):
        mesh = inflate_curve_ridge(self.points, self.normals, self.profile)
        boundary = backing_vertex_indices(mesh)
        self.assertTrue(all(abs(mesh.vertices[index][2]) < 1.0e-9 for index in boundary))

    def test_interior_profile_inflates_along_host_normal(self):
        mesh = inflate_curve_ridge(self.points, self.normals, self.profile)
        center = mesh.vertices[mesh.ring_size + 2]
        self.assertAlmostEqual(center[2], self.profile.depth)

    def test_relaxation_sags_only_free_bulge(self):
        mesh = inflate_curve_ridge(self.points, self.normals, self.profile)
        fixed = backing_vertex_indices(mesh) + commissure_vertex_indices(mesh)
        solved = geometric_curve_relaxation(mesh, 0.5, (0, -1, 0), fixed, profile_depth=self.profile.depth)
        self.assertLess(solved[mesh.ring_size + 2][1], mesh.vertices[mesh.ring_size + 2][1])
        self.assertTrue(all(solved[index] == mesh.vertices[index] for index in fixed))

    def test_cyclic_curve_connects_last_ring_without_caps(self):
        profile = CurveRidgeProfile(profile_segments=5, cyclic=True)
        mesh = inflate_curve_ridge(self.points, self.normals, profile)
        self.assertEqual(len(mesh.faces), len(self.points) * profile.profile_segments)

    def test_attachment_masks_cover_backing_and_commissures(self):
        mesh = inflate_curve_ridge(self.points, self.normals, self.profile)
        self.assertEqual(len(backing_vertex_indices(mesh)), 6)
        self.assertEqual(len(commissure_vertex_indices(mesh)), 10)

    def test_invalid_curve_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "matching point and normal arrays"):
            inflate_curve_ridge(self.points, self.normals[:1], self.profile)


if __name__ == "__main__":
    unittest.main()
