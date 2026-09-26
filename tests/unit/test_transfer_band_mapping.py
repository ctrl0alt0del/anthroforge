import unittest
import numpy as np
from core.authoring.errors import AuthoringError
from core.authoring.transfer_band_mapping import frame, guesses, project


class TransferBandMappingTests(unittest.TestCase):
    def test_rotated_scaled_frame_and_native_region_projection(self):
        mapping = dict(source_frame=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                       target_frame=[[3, 0, 0], [3, 2, 0], [1, 0, 0]], max_distance=.3)
        vertices = np.array([[.2, .2, .1], [.5, .3, .1]])
        expected = [[2.6, .4, .2], [2.4, 1., .2]]
        np.testing.assert_allclose(guesses(vertices, mapping), expected)
        polygons = [[[2, 0, 0], [3, 0, 0], [3, 2, 0], [2, 2, 0]]]
        result, report = project(vertices, polygons, mapping)
        np.testing.assert_allclose(result, np.array(expected)*[1, 1, 0], atol=1e-10)
        self.assertAlmostEqual(report['max_projection_distance'], .2)
        with self.assertRaises(AuthoringError): project(vertices, polygons, dict(mapping, max_distance=.1))

    def test_invalid_frames_rejected(self):
        for points in [[[0, 0, 0]]*3, [[0, 0, 0], [1, 0, 0], [2, 0, 0]], [[0, 0, 0], [1, 0, 0], [0, float('nan'), 0]]]:
            with self.assertRaises(AuthoringError): frame(points)
