import unittest
import numpy as np
from core.authoring.smooth_holdout import expected_mesh


def fixture():
    controls = np.array([[[x, y, 0] for y in np.linspace(0, 1, 4)] for x in (0, 1)], float)
    fibers = [dict(path=[[x, -1, 0], [x, 0, 0], [x, 1, 0], [x, 2, 0]], stations=[-1, 0, 1, 2]) for x in (0, 1)]
    return dict(controls=controls.tolist(), fibers=fibers)


class SmoothHoldoutTests(unittest.TestCase):
    def test_expected_surface_contains_declared_extensions(self):
        vertices, triangles = expected_mesh(fixture())
        np.testing.assert_allclose(vertices.min(axis=0), [0, -1, 0])
        np.testing.assert_allclose(vertices.max(axis=0), [1, 2, 0])
        self.assertTrue(len(triangles) > 100)

    def test_body_is_evaluated_independently_from_native_path(self):
        part = fixture(); part['fibers'][0]['path'][1][2] = 5
        vertices, _ = expected_mesh(part)
        self.assertEqual(float(vertices[:, 2].max()), 0)
