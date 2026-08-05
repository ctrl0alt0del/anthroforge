import tempfile
import unittest
from pathlib import Path

import numpy as np

from core.topology.density import corrected_target, internal_target, needs_correction
from core.topology.budgets import build_regions, density_errors, density_field, smooth_target_lengths
from core.topology.model import (
    SymmetryPlane, TopologyCapture, TopologyDensityRule, TopologyGuide,
    TopologyOwnershipSource, TopologyResult, TopologySettings, TopologyValidationReport,
)
from core.topology.ownership import assign_ownership, vertex_areas
from core.topology.refine import refine_quads
from core.topology.refinement import muscle_proximity_weights, muscle_target_lengths
from core.topology.protocol import capture_hash, read_capture, read_result, write_capture, write_result
from core.topology.symmetry import normalized_plane, reflect_points, signed_distances
from core.topology.validation import validate_topology
from adapters.topology.density_runtime import budget_warnings
from adapters.topology.refinement_runtime import has_muscle_refinement


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
        rules = (_rule(0, "scp", "", "SUBTREE_BUDGET", 4000),)
        sources = (_ownership_source(0, "SCP", "scp", ("scp",), 0.0),)
        digest = capture_hash("AF_ROOT", vertices, faces, (guide,), settings, plane, rules, sources)
        capture = TopologyCapture("AF_ROOT", vertices, faces, (guide,), np.zeros(3),
                                  np.ones(3), digest, settings, plane, (), rules, sources)
        report = TopologyValidationReport(*([True] * 12))
        result = TopologyResult(np.zeros((4, 3)), np.asarray(((0, 1, 2, 3),)),
                                np.zeros(1), -np.ones(1), {"ok": True}, report)
        with tempfile.TemporaryDirectory() as folder:
            capture_path, result_path = Path(folder, "input.npz"), Path(folder, "result.npz")
            write_capture(capture_path, capture); write_result(result_path, result)
            loaded_capture, loaded_result = read_capture(capture_path), read_result(result_path)
        self.assertEqual(loaded_capture.input_hash, digest)
        self.assertEqual(loaded_capture.guides[0].fiber_id, "F1")
        self.assertEqual(loaded_capture.density_rules, rules)
        self.assertEqual(loaded_capture.ownership_sources[0].owner_scp_ids, ("scp",))
        self.assertTrue(loaded_result.validation.valid)
        self.assertEqual(len(loaded_result.skin_binding.triangle_indices), 4)

    def test_validation_accepts_orientable_quad_patch(self):
        vertices = np.asarray(((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)), dtype=float)
        report = validate_topology(vertices, np.asarray(((0, 1, 2, 3),), dtype=np.int32))
        self.assertTrue(report.valid, report.message)

    def test_validation_rejects_non_quads(self):
        vertices = np.eye(3)
        report = validate_topology(vertices, np.asarray(((0, 1, 2),), dtype=np.int32))
        self.assertFalse(report.valid)

    def test_nested_subtree_budgets_are_inclusive(self):
        rules = _density_rules()
        owners, areas = np.asarray((0, 1, 2)), np.ones(3)
        regions = {item.scp_id: item for item in build_regions(rules, 9000, owners, areas)}
        self.assertEqual(regions[""].exclusive_quads, 5000)
        self.assertEqual(regions["cranium"].exclusive_quads, 1500)
        self.assertEqual(regions["face"].exclusive_quads, 2500)

    def test_budget_validation_rejects_oversubscription(self):
        rules = (_rule(0, "body", "", "INHERIT", 0),
                 _rule(1, "cranium", "body", "SUBTREE_BUDGET", 9500))
        self.assertTrue(density_errors(rules, 9000))

    def test_budget_warning_reports_large_approximation(self):
        values = ({"scp_id": "cranium", "requested_exclusive_quads": 4000,
                   "actual_exclusive_quads": 3000},)
        self.assertIn("3000/4000", budget_warnings(values)[0])

    def test_ownership_resolves_nearest_scp_and_vcp_candidates(self):
        sources = (_ownership_source(0, "SCP", "left", ("left",), 0.0),
                   _ownership_source(1, "SCP", "right", ("right",), 10.0),
                   _ownership_source(2, "MUSCLE", "muscle", ("left", "right"), 5.0))
        vertices = np.asarray(((0, 0, 0), (5, 0, 0), (10, 0, 0), (5, 1, 0)), dtype=float)
        faces = np.asarray(((0, 1, 3), (1, 2, 3)), dtype=np.int32)
        rules = (_rule(0, "left", "", "INHERIT", 0), _rule(1, "right", "", "INHERIT", 0))
        result = assign_ownership(vertices, faces, sources, rules)
        self.assertEqual((result.owner_indices[0], result.owner_indices[2]), (0, 1))

    def test_density_smoothing_preserves_region_predictions(self):
        vertices = np.asarray(((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)), dtype=float)
        faces = np.asarray(((0, 1, 2), (0, 2, 3)), dtype=np.int32)
        rules = (_rule(0, "left", "", "SUBTREE_BUDGET", 100),)
        areas = vertex_areas(vertices, faces); regions = build_regions(rules, 200, np.zeros(4), areas)
        field = density_field(regions, 4)
        smoothed = smooth_target_lengths(field.target_edge_lengths, faces, areas, regions)
        self.assertTrue(np.isfinite(smoothed).all())

    def test_conforming_refinement_keeps_only_quads(self):
        vertices = np.asarray(((0, 0, 0), (1, 0, 0), (2, 0, 0),
                               (0, 1, 0), (1, 1, 0), (2, 1, 0)), dtype=float)
        faces = np.asarray(((0, 1, 4, 3), (1, 2, 5, 4)), dtype=np.int32)
        points, refined, parents = refine_quads(vertices, faces, (True, False))
        self.assertEqual(refined.shape, (6, 4))
        self.assertTrue(np.isfinite(points).all())
        self.assertEqual(tuple(np.bincount(parents)), (4, 2))

    def test_muscle_proximity_increases_local_density(self):
        distances = np.asarray((0.0, 0.03, 0.1))
        weights = muscle_proximity_weights(distances, 1.0)
        lengths = muscle_target_lengths(np.ones(3), weights)
        self.assertLess(lengths[0], lengths[1])
        self.assertLess(lengths[1], lengths[2])
        self.assertAlmostEqual(lengths[2], 1.0)

    def test_muscle_strategy_requires_captured_muscle(self):
        settings = TopologySettings(refinement_strategy="MUSCLE_PROXIMITY")
        capture = TopologyCapture("Root", np.eye(3), np.asarray(((0, 1, 2),)), (),
                                  np.zeros(3), np.ones(3), "hash", settings)
        self.assertFalse(has_muscle_refinement(capture))
        source = _ownership_source(0, "MUSCLE", "M1", (), 0.0)
        capture = TopologyCapture("Root", np.eye(3), np.asarray(((0, 1, 2),)), (),
                                  np.zeros(3), np.ones(3), "hash", settings,
                                  ownership_sources=(source,))
        self.assertTrue(has_muscle_refinement(capture))


def _rule(index, scp_id, parent, mode, quads):
    return TopologyDensityRule(index, scp_id, parent, mode, quads)


def _density_rules():
    return (_rule(0, "body", "", "INHERIT", 0),
            _rule(1, "cranium", "body", "SUBTREE_BUDGET", 4000),
            _rule(2, "face", "cranium", "SUBTREE_BUDGET", 2500))


def _ownership_source(index, kind, entity_id, owners, x_value):
    vertices = np.asarray(((x_value, 0, 0), (x_value, 1, 0), (x_value, 0, 1)), dtype=float)
    return TopologyOwnershipSource(index, kind, entity_id, "ORIGINAL", owners,
                                   vertices, np.asarray(((0, 1, 2),), dtype=np.int32))


if __name__ == "__main__":
    unittest.main()
