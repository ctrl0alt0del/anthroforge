import unittest
from types import SimpleNamespace

import numpy as np

from core.vcp.v2.roadmap_corner_geometry import (
    roadmap_corner_candidate, roadmap_corner_window)
from core.vcp.v2.pin_smoothing_geometry import turn_metrics


def _span(branch="ROADMAP"):
    return SimpleNamespace(first_edge=0, edge_count=8,
                           branch=SimpleNamespace(value=branch))


def _corner():
    left = [(0.0, 0.0, float(index)) for index in range(5)]
    right = [(float(index), 0.0, 4.0) for index in range(1, 5)]
    return np.asarray(left + right, dtype=np.float64)


class FiberRoadmapCornerGeometryTests(unittest.TestCase):
    def test_selects_worst_free_roadmap_corner(self):
        window = roadmap_corner_window(_corner(), (0, 8), (_span(),), 3, 45.0)
        self.assertEqual((window.left, window.corner, window.right), (1, 4, 7))

    def test_candidate_preserves_window_boundaries_and_smooths(self):
        points = _corner(); window = roadmap_corner_window(points, (0, 8), (_span(),), 3, 45.0)
        candidate = roadmap_corner_candidate(points, window)
        self.assertTrue(np.array_equal(candidate[[0, 1, 7, 8]], points[[0, 1, 7, 8]]))
        self.assertLess(turn_metrics(candidate)[0], 0.5 * turn_metrics(points)[0])

    def test_nonroadmap_and_pinned_corners_are_skipped(self):
        points = _corner()
        self.assertIsNone(roadmap_corner_window(points, (0, 8), (_span("DIRECT"),)))
        self.assertIsNone(roadmap_corner_window(points, (0, 4, 8), (_span(),)))


if __name__ == "__main__":
    unittest.main()
