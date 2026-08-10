import unittest

from core.vcp.soft_tissue_surface_field import boundary_falloff_weights


def grid_fixture():
    vertices = [(float(x), float(y), 0.0) for y in range(3) for x in range(4)]
    vertices[5] = (1.0, 0.1, 0.0)
    faces = [(y * 4 + x, y * 4 + x + 1, (y + 1) * 4 + x + 1, (y + 1) * 4 + x)
             for y in range(2) for x in range(3)]
    edges = sorted({tuple(sorted((face[i], face[(i + 1) % 4]))) for face in faces for i in range(4)})
    return vertices, edges, faces


class SoftTissueSurfaceFieldTests(unittest.TestCase):
    def test_open_surface_uses_normalized_shortest_edge_distance(self):
        vertices, edges, faces = grid_fixture()
        weights = boundary_falloff_weights(len(vertices), edges, faces, vertices)
        self.assertGreater(weights[5], 0.0)
        self.assertLess(weights[5], weights[6])
        self.assertAlmostEqual(weights[6], 1.0)
        self.assertTrue(all(weights[index] == 0.0 for index in (0, 1, 2, 3, 4, 7, 8, 9, 10, 11)))

    def test_closed_surface_uses_uniform_weight(self):
        vertices = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))
        faces = ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3))
        edges = sorted({tuple(sorted((face[i], face[(i + 1) % 3]))) for face in faces for i in range(3)})
        self.assertEqual(boundary_falloff_weights(4, edges, faces, vertices), (1.0, 1.0, 1.0, 1.0))


if __name__ == "__main__":
    unittest.main()
