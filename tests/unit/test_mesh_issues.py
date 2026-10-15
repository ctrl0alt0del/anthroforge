"""Quality warnings do not bypass consumer contracts or cancellation."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from core.mesh_issues import require_mesh, annotate, restore_report
from core.mesh_diagnostics import intersections, check_result
from core.draft_skin.model import SkinResult, SkinValidationReport
from workers.stage_results import checkpoint, failed_stage


def mesh():
    v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
    report = SkinValidationReport(False, True, True, False, True, False, True, True, "Open surface")
    return SkinResult(v, np.array([[0, 1, 2]]), np.zeros(3), {}, report)


class MeshIssueTests(unittest.TestCase):
    def test_repeated_intersection_check_does_not_duplicate_findings(self):
        with patch("core.mesh_diagnostics.intersections", return_value={"self_intersections": 2}):
            result = check_result(check_result(mesh()))
        self.assertEqual(result.validation.message.count("Self-intersections:"), 1)

    def test_quality_failure_is_recorded_and_publishable(self):
        result = annotate(mesh(), "skin")
        self.assertFalse(result.validation.valid)
        self.assertIn("QUALITY_WATERTIGHT", {row["code"] for row in result.statistics["issues"]})
        self.assertFalse(restore_report(result.statistics, SkinValidationReport).valid)
        self.assertIsNone(restore_report({}, SkinValidationReport))

    def test_structural_errors_remain_blocking(self):
        for points, faces in (([[np.nan, 0, 0]], [[0, 0, 0]]), ([[0, 0, 0]], [[0, 1, 2]]), ([], [])):
            with self.assertRaises(ValueError):
                require_mesh(points, faces)

    def test_partial_stage_survives_later_failure_but_cancellation_does_not_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            spec = SimpleNamespace(job_dir=folder, cancel_path=folder+"/cancel", summary_path=folder+"/summary.json",
                                   skin_result_path=folder+"/skin.npz", topology_result_path=folder+"/topology.npz")
            checkpoint(spec, mesh(), "skin", "rebuilt")
            self.assertTrue(failed_stage(spec, ValueError("No usable topology")))
            Path(spec.cancel_path).touch()
            self.assertFalse(failed_stage(spec, ValueError("Cancelled")))
            self.assertTrue(Path(spec.skin_result_path).exists())

    def test_native_crossing_and_contact_are_different(self):
        a = np.array([[-1,-1,0], [1,-1,0], [0,1,0]], float)
        crossing = np.array([[0,-.5,-1], [0,-.5,1], [0,.5,0]], float)
        faces = np.array([[0,1,2], [3,4,5]])
        self.assertEqual(intersections(np.vstack((a, crossing)), faces)["self_intersections"], 1)
        contact = intersections(np.vstack((a, a)), faces)
        self.assertEqual(contact["self_intersections"], 0)
        self.assertEqual(contact["contact_pairs"], 1)

    def test_native_memory_and_cancellation_are_explicit(self):
        result = mesh()
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            intersections(result.vertices, result.triangles, budget=1)
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            intersections(result.vertices, result.triangles, cancelled=lambda: True)
