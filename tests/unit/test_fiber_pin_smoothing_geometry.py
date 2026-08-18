import unittest

import numpy as np

from core.vcp.v2.pin_smoothing_geometry import (curvature_energy,
    pin_interpolating_candidate, smoothing_candidate, smoothing_windows, surface_tangent_candidate,
    turn_metrics, window_turn_peak)


def _kinked():
    return np.asarray(((0, 0, 0), (1, 0, 0), (2, 0, 0),
                       (2, 1, 0), (2, 2, 0), (3, 2, 0), (4, 2, 0)), dtype=np.float64)


class FiberPinSmoothingGeometryTests(unittest.TestCase):
    def test_candidate_preserves_every_pin(self):
        points = _kinked(); pins = (0, 2, 4, 6)
        result = smoothing_candidate(points, pins, smoothing_windows(points, pins, 2, 1.0))
        np.testing.assert_array_equal(result[list(pins)], points[list(pins)])

    def test_candidate_reduces_arc_length_weighted_curvature(self):
        points = _kinked(); pins = (0, 2, 4, 6)
        result = smoothing_candidate(points, pins, smoothing_windows(points, pins, 2, 1.0))
        self.assertLess(curvature_energy(result, points), curvature_energy(points, points))

    def test_candidate_reduces_worst_turn(self):
        points = _kinked(); pins = (0, 2, 4, 6)
        result = smoothing_candidate(points, pins, smoothing_windows(points, pins, 2, 1.0))
        self.assertLess(turn_metrics(result)[0], turn_metrics(points)[0])

    def test_windows_skip_already_smooth_curve(self):
        points = np.column_stack((np.arange(7.0), np.zeros((7, 2))))
        self.assertEqual(smoothing_windows(points, (0, 3, 6), 2, 1.0), ())

    def test_surface_tangent_candidate_preserves_pin_and_reduces_pin_turn(self):
        points = _kinked(); window = smoothing_windows(points, (0, 2, 4, 6), 2, 1.0)[1]
        result = surface_tangent_candidate(points, window, (0, 0, 1), "incoming", 1.5)
        np.testing.assert_array_equal(result[window.pin], points[window.pin])
        self.assertLess(turn_metrics(result[1:4])[0], turn_metrics(points[1:4])[0])

    def test_pin_interpolating_candidate_is_global_and_pin_exact(self):
        points = _kinked(); pins = (0, 2, 4, 6)
        result = pin_interpolating_candidate(points, pins, 1.5)
        np.testing.assert_array_equal(result[list(pins)], points[list(pins)])
        self.assertLess(turn_metrics(result)[0], turn_metrics(points)[0])


if __name__ == "__main__":
    unittest.main()
