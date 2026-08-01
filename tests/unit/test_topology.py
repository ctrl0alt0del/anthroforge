import tempfile
import unittest
from pathlib import Path

import numpy as np

from core.topology.density import corrected_target, internal_target, needs_correction
from core.topology.model import (
    SymmetryPlane, TopologyCapture, TopologyGuide, TopologyResult,
    TopologySettings, TopologyValidationReport,
)
from core.topology.protocol import capture_hash, read_capture, read_result, write_capture, write_result
from core.topology.symmetry import normalized_plane, reflect_points, signed_distances
from core.topology.validation import validate_topology


class TopologyTests(unittest.TestCase):
    def test_arbitrary_plane_reflection(self):
        plane = normalized_plane((2, 1, 0), (1, 1, 0))
        points = np.asarray(((3, 1, 0), (2, 2, 0)), dtype=float)
        reflected = reflect_points(points, plane)
        np.testing.assert_allclose(signed_distances(reflected, plane), -signed_distances(points, plane))

    def test_density_maps_accepted_target(self):
        self.assertEqual(internal_target(8100), 900)
        self.assertTrue(needs_correction(6000, 8100))
        self.assertEqual(corrected_target(900, 6000, 8100), 1215)

    def test_protocol_round_trip(self):
        settings = TopologySettings(8100, "CUSTOM", (1, 2, 3), (0, 1, 0))
        plane = SymmetryPlane(np.asarray((1, 2, 3.0)), np.asarray((0, 1, 0.0)))
        guide = TopologyGuide(0, "F1", "Guide", "ORIGINAL", np.eye(3))
        vertices, faces = np.eye(3), np.asarray(((0, 1, 2),), dtype=np.int32)
        digest = capture_hash("AF_ROOT", vertices, faces, (guide,), settings, plane)
        capture = TopologyCapture("AF_ROOT", vertices, faces, (guide,), np.zeros(3),
                                  np.ones(3), digest, settings, plane)
        report = TopologyValidationReport(*([True] * 12))
        result = TopologyResult(np.zeros((4, 3)), np.asarray(((0, 1, 2, 3),)),
                                np.zeros(1), -np.ones(1), {"ok": True}, report)
        with tempfile.TemporaryDirectory() as folder:
            capture_path, result_path = Path(folder, "input.npz"), Path(folder, "result.npz")
            write_capture(capture_path, capture); write_result(result_path, result)
            loaded_capture, loaded_result = read_capture(capture_path), read_result(result_path)
        self.assertEqual(loaded_capture.input_hash, digest)
        self.assertEqual(loaded_capture.guides[0].fiber_id, "F1")
        self.assertTrue(loaded_result.validation.valid)

    def test_validation_accepts_orientable_quad_patch(self):
        vertices = np.asarray(((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)), dtype=float)
        report = validate_topology(vertices, np.asarray(((0, 1, 2, 3),), dtype=np.int32))
        self.assertTrue(report.valid, report.message)

    def test_validation_rejects_non_quads(self):
        vertices = np.eye(3)
        report = validate_topology(vertices, np.asarray(((0, 1, 2),), dtype=np.int32))
        self.assertFalse(report.valid)


if __name__ == "__main__":
    unittest.main()
