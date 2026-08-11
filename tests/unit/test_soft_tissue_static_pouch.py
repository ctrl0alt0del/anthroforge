import unittest

from core.vcp.soft_tissue_static_pouch import (
    StaticPouchSettings,
    StaticTether,
    constraint_pass_stiffness,
    mesh_volume,
    solve_static_pouch,
    solve_static_tissue,
    triangulate_faces,
)


def cube_fixture():
    vertices = ((-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0),
                (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))
    faces = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
    return vertices, faces


class SoftTissueStaticPouchTests(unittest.TestCase):
    def test_tether_strength_is_iteration_independent(self):
        expected, iterations, passes = 0.65, 110, 4
        per_pass = constraint_pass_stiffness(expected, iterations, passes)
        aggregate = 1.0 - (1.0 - per_pass) ** (iterations * passes)
        self.assertAlmostEqual(aggregate, expected, places=12)

    def test_gravity_moves_free_vertices_and_keeps_fixed_vertices(self):
        vertices, faces = cube_fixture()
        settings = StaticPouchSettings(20, 2, 0.01, 0.25, 0.0, (1.0, 0.0, 0.0))
        solved = solve_static_pouch(vertices, faces, (0, 1, 2, 3), settings)
        self.assertEqual(solved[:4], tuple(tuple(float(v) for v in p) for p in vertices[:4]))
        self.assertGreater(sum(point[0] for point in solved[4:]), sum(point[0] for point in vertices[4:]))

    def test_volume_constraint_limits_volume_change(self):
        vertices, faces = cube_fixture()
        settings = StaticPouchSettings(30, 3, 0.01, 0.4, 0.9, (1.0, 0.0, -1.0))
        solved = solve_static_pouch(vertices, faces, (0, 1, 2, 3), settings)
        triangles = triangulate_faces(faces)
        before, after = abs(mesh_volume(vertices, triangles)), abs(mesh_volume(solved, triangles))
        self.assertLess(abs(after - before) / before, 0.05)

    def test_tether_reduces_free_vertex_displacement(self):
        vertices, faces = cube_fixture()
        settings = StaticPouchSettings(20, 2, 0.01, 0.2, 0.0, (1.0, 0.0, 0.0))
        loose = solve_static_pouch(vertices, faces, (0, 1, 2, 3), settings)
        tether = StaticTether(6, vertices[6], 0.0, 0.5)
        held = solve_static_pouch(vertices, faces, (0, 1, 2, 3), settings, (tether,))
        self.assertLess(abs(held[6][0] - vertices[6][0]), abs(loose[6][0] - vertices[6][0]))

    def test_invalid_tether_is_rejected(self):
        vertices, faces = cube_fixture()
        tether = StaticTether(99, (0.0, 0.0, 0.0), 0.0)
        with self.assertRaisesRegex(ValueError, "tether vertex index"):
            solve_static_pouch(vertices, faces, (), StaticPouchSettings(), (tether,))

    def test_large_tolerance_cannot_cancel_gravity_iterations(self):
        vertices, faces = cube_fixture()
        settings = StaticPouchSettings(10, 1, 0.01, 0.0, 0.0, (1.0, 0.0, 0.0))
        result = solve_static_tissue(vertices, faces, (0, 1, 2, 3), settings, tolerance=10.0)
        self.assertEqual(result.iterations, 10)
        self.assertAlmostEqual(result.max_displacement, 0.1)

if __name__ == "__main__":
    unittest.main()
