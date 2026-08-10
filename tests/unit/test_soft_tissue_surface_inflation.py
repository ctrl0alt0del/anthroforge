import unittest

from core.vcp.soft_tissue_surface_inflation import (
    SurfaceLayerProfile,
    backing_vertex_indices,
    inflate_surface_layer,
    perimeter_vertex_indices,
)


class SoftTissueSurfaceInflationTests(unittest.TestCase):
    def setUp(self):
        self.points = ((0.0, 0.0, 0.0), (-1.0, -1.0, 0.0), (1.0, -1.0, 0.0),
                       (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0))
        self.normals = ((0.0, 0.0, 1.0),) * 5
        self.faces = ((0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 1))
        self.boundary = ((1, 2), (2, 3), (3, 4), (4, 1))
        self.weights = (1.0, 0.0, 0.0, 0.0, 0.0)

    def test_surface_inflates_into_closed_layer(self):
        mesh = inflate_surface_layer(self.points, self.normals, self.faces, self.boundary,
                                     self.weights, SurfaceLayerProfile())
        self.assertEqual((len(mesh.vertices), len(mesh.faces), mesh.base_vertex_count), (10, 12, 5))

    def test_thickness_field_controls_normal_inflation(self):
        profile = SurfaceLayerProfile(max_thickness=0.2, min_thickness=0.01)
        mesh = inflate_surface_layer(self.points, self.normals, self.faces, self.boundary, self.weights, profile)
        self.assertAlmostEqual(mesh.vertices[0][2], 0.2)
        self.assertAlmostEqual(mesh.vertices[1][2], 0.01)

    def test_backing_remains_on_base_surface(self):
        mesh = inflate_surface_layer(self.points, self.normals, self.faces, self.boundary,
                                     self.weights, SurfaceLayerProfile())
        self.assertEqual(tuple(mesh.vertices[index] for index in backing_vertex_indices(mesh)), self.points)

    def test_attachment_masks_cover_backing_and_perimeter(self):
        mesh = inflate_surface_layer(self.points, self.normals, self.faces, self.boundary,
                                     self.weights, SurfaceLayerProfile())
        self.assertEqual(backing_vertex_indices(mesh), (5, 6, 7, 8, 9))
        self.assertEqual(perimeter_vertex_indices(mesh, self.boundary), (1, 2, 3, 4, 6, 7, 8, 9))

    def test_invalid_weight_is_rejected(self):
        weights = (1.2,) + self.weights[1:]
        with self.assertRaisesRegex(ValueError, "weights must be between"):
            inflate_surface_layer(self.points, self.normals, self.faces, self.boundary, weights, SurfaceLayerProfile())


if __name__ == "__main__":
    unittest.main()
