import unittest

import numpy as np

from core.vcp.soft_tissue_static_envelope import StaticEnvelopeSettings, solve_static_envelope
from core.vcp.soft_tissue_static_pouch import StaticTether, mesh_volume, triangulate_faces
from core.vcp.soft_tissue_surface_inflation import SurfaceLayerProfile, inflate_surface_layer


def envelope_fixture(amount, size=7):
    points = tuple((0.0, float(y), float(z)) for z in np.linspace(-1.0, 1.0, size)
                   for y in np.linspace(-1.0, 1.0, size))
    normals = ((-1.0, 0.0, 0.0),) * len(points)
    faces = tuple((z * size + y, z * size + y + 1, (z + 1) * size + y + 1,
                   (z + 1) * size + y) for z in range(size - 1) for y in range(size - 1))
    boundary = tuple((index, index + 1) for index in range(size - 1))
    boundary += tuple(((size - 1) * size + index, (size - 1) * size + index + 1)
                      for index in range(size - 1))
    boundary += tuple((index * size, (index + 1) * size) for index in range(size - 1))
    boundary += tuple((index * size + size - 1, (index + 1) * size + size - 1)
                      for index in range(size - 1))
    weights = tuple((1.0 - max(abs(point[1]), abs(point[2]))) ** 0.6 for point in points)
    mesh = inflate_surface_layer(points, normals, faces, boundary, weights,
                                 SurfaceLayerProfile(amount, 0.01, 1.0))
    rim = {index for edge in boundary for index in edge}
    fixed = tuple(sorted(rim | set(range(len(points), len(points) * 2))))
    return mesh, fixed


def solve_fixture(amount, iterations=160, sagginess=1.0):
    mesh, fixed = envelope_fixture(amount)
    settings = StaticEnvelopeSettings(iterations, 6, 0.0015 * sagginess, 0.48, 0.88)
    result = solve_static_envelope(mesh.vertices, mesh.faces, fixed, mesh.base_vertex_count,
                                   settings, tolerance=1.0e-6)
    return mesh, fixed, result


class StaticEnvelopeTests(unittest.TestCase):
    def test_fixed_backing_and_rim_are_exact(self):
        mesh, fixed, result = solve_fixture(0.8)
        for index in fixed:
            self.assertEqual(result.vertices[index], mesh.vertices[index])

    def test_default_retention_preserves_target_volume(self):
        mesh, _fixed, result = solve_fixture(0.8)
        triangles = triangulate_faces(mesh.faces)
        before = abs(mesh_volume(mesh.vertices, triangles))
        after = abs(mesh_volume(result.vertices, triangles))
        self.assertLess(abs(after - before) / before, 5.0e-5)

    def test_gravity_never_moves_tangent_surface_upward(self):
        mesh, _fixed, result = solve_fixture(0.8)
        count = mesh.base_vertex_count
        rise = [result.vertices[index][2] - mesh.vertices[index][2] for index in range(count)]
        self.assertLessEqual(max(rise), 1.0e-9)
        self.assertLess(min(rise), -0.05)

    def test_larger_amount_has_greater_centroid_drop(self):
        small, _fixed, small_result = solve_fixture(0.8)
        large, _fixed, large_result = solve_fixture(2.4)
        small_drop = _centroid_drop(small, small_result)
        large_drop = _centroid_drop(large, large_result)
        self.assertGreater(large_drop, small_drop * 1.25)

    def test_surface_slack_allows_more_gravity_redistribution(self):
        mesh, fixed = envelope_fixture(1.6)
        taut = _solve_with_slack(mesh, fixed, 0.0)
        slack = _solve_with_slack(mesh, fixed, 0.5)
        self.assertGreater(_centroid_drop(mesh, slack), _centroid_drop(mesh, taut) * 1.05)

    def test_zero_sagginess_retains_a_pressure_shape(self):
        mesh, _fixed, result = solve_fixture(0.8, sagginess=0.0)
        count = mesh.base_vertex_count
        depths = [-result.vertices[index][0] for index in range(count)]
        self.assertGreater(max(depths), 0.3)

    def test_invalid_tether_is_rejected(self):
        mesh, fixed = envelope_fixture(0.8)
        tether = StaticTether(999, (0.0, 0.0, 0.0), 0.0, 0.5)
        with self.assertRaisesRegex(ValueError, "constraint index"):
            solve_static_envelope(mesh.vertices, mesh.faces, fixed, mesh.base_vertex_count,
                                  StaticEnvelopeSettings(), (tether,))


def _centroid_drop(mesh, result):
    count = mesh.base_vertex_count
    before = sum(mesh.vertices[index][2] for index in range(count)) / count
    after = sum(result.vertices[index][2] for index in range(count)) / count
    return before - after


def _solve_with_slack(mesh, fixed, slack):
    settings = StaticEnvelopeSettings(160, 6, 0.0015, 0.48, 0.88, surface_slack=slack)
    return solve_static_envelope(mesh.vertices, mesh.faces, fixed, mesh.base_vertex_count,
                                 settings, tolerance=1.0e-6)


if __name__ == "__main__":
    unittest.main()
