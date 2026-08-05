from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from adapters.draft_skin.capture import _base_collagen, _include_fiber
from adapters.draft_skin import jobs
from core.draft_skin.fields import collagen_field
from core.draft_skin.grid import choose_resolution, estimated_bytes, grid_spec
from core.draft_skin.mesh import orient_outward
from core.draft_skin.model import SkinCapture, SkinJobStatus, SkinResult, SkinSolverSettings, SkinSource
from core.draft_skin.protocol import (
    capture_hash,
    read_capture,
    read_result,
    read_status,
    write_capture,
    write_job,
    write_result,
    write_status,
)
from core.draft_skin.solver import solve_capture
from core.draft_skin.settings import (
    DEFAULT_SETTINGS,
    padding_ratio,
    resolved_solver_distances,
    settings_from_percentages,
    settings_payload,
    settings_percentages,
)
from core.draft_skin.status import SkinCancelled
from core.draft_skin.validation import validate_mesh


def cube_mesh():
    vertices = np.asarray([
        (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
        (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
    ], dtype=np.float32)
    faces = np.asarray([
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7),
    ], dtype=np.int32)
    return vertices, orient_outward(vertices, faces)


class FakeScene:
    def as_pointer(self):
        return id(self)


class FakeProcess:
    def __init__(self, result=None):
        self.terminated = False
        self.result = result

    def poll(self):
        return self.result

    def terminate(self):
        self.terminated = True


class DraftSkinTests(unittest.TestCase):
    def test_auto_collagen_uses_legacy_semantics(self):
        automatic = SimpleNamespace(skin_collagen_mode="AUTO", name="Ear")
        uniform = SimpleNamespace(skin_collagen_mode="UNIFORM", skin_collagen=0.35, name="Ear")
        self.assertEqual(_base_collagen(automatic, SimpleNamespace(name="Geometry")), 0.0)
        self.assertAlmostEqual(_base_collagen(uniform, SimpleNamespace(name="Geometry")), 0.35)

    def test_fiber_fallback_only_when_surface_is_missing(self):
        fibers = {"F1": SimpleNamespace(muscle_id="M1"), "F2": SimpleNamespace(muscle_id="")}
        first = {"af_fiber_id": "F1"}
        second = {"af_fiber_id": "F2"}
        self.assertFalse(_include_fiber(first, fibers, {"M1"}))
        self.assertTrue(_include_fiber(first, fibers, set()))
        self.assertTrue(_include_fiber(second, fibers, {"M1"}))

    def test_collagen_field_spreads_zero_seed(self):
        surface = np.zeros((31, 31, 31), dtype=bool)
        seeds = np.full(surface.shape, np.inf, dtype=np.float32)
        surface[15, 15, 15] = True
        seeds[15, 15, 15] = 0.0
        field = collagen_field(surface, seeds, 1.0)
        self.assertEqual(field[15, 15, 15], 0.0)
        self.assertGreater(field[29, 29, 29], 0.99)

    def test_zero_collagen_falloff_width_stays_finite(self):
        surface = np.zeros((7, 7, 7), dtype=bool)
        seeds = np.full(surface.shape, np.inf, dtype=np.float32)
        surface[3, 3, 3], seeds[3, 3, 3] = True, 0.0
        field = collagen_field(surface, seeds, 1.0, 0.0, 0.0)
        self.assertTrue(np.isfinite(field).all())

    def test_default_settings_preserve_accepted_voxel_distances(self):
        values = resolved_solver_distances(DEFAULT_SETTINGS, 220.0)
        self.assertAlmostEqual(values["required_offset"], 1.189424086064195)
        self.assertAlmostEqual(values["rest_offset"], 3.1717975628378534)
        self.assertAlmostEqual(values["collagen_inner"], 4.75769634425678)
        self.assertAlmostEqual(values["collagen_outer"], 13.480139642060877)
        self.assertAlmostEqual(padding_ratio(DEFAULT_SETTINGS) * 220.0, 18.27308903277034)

    def test_percentage_settings_round_trip(self):
        settings = settings_from_percentages(0.5, 0.9, 2.1, 4.0)
        values = settings_percentages(settings)
        self.assertEqual(tuple(round(value, 6) for value in values.values()), (0.5, 0.9, 2.1, 4.0))

    def test_cube_validation_accepts_closed_outward_mesh(self):
        vertices, faces = cube_mesh()
        report = validate_mesh(vertices, faces, True)
        self.assertTrue(report.valid, report.message)

    def test_protocol_round_trips_capture_and_result(self):
        vertices, faces = cube_mesh()
        source = SkinSource(0, "SCP", "S1", "ORIGINAL", "Cube", vertices, faces, np.ones(8))
        digest = capture_hash("ROOT", (source,))
        settings = SkinSolverSettings(0.01, 0.02, 0.03, 0.04)
        digest = capture_hash("ROOT", (source,), settings)
        capture = SkinCapture(
            "ROOT", (source,), vertices.min(0), vertices.max(0), digest, 1 / 220, settings=settings
        )
        result = SkinResult(vertices, faces, np.ones(8), {"input_hash": digest}, validate_mesh(vertices, faces))
        with tempfile.TemporaryDirectory() as folder:
            input_path, result_path = Path(folder) / "input.npz", Path(folder) / "result.npz"
            write_capture(input_path, capture)
            write_result(result_path, result)
            loaded_capture, loaded_result = read_capture(input_path), read_result(result_path)
        self.assertEqual((loaded_capture.input_hash, loaded_result.statistics["input_hash"]), (digest, digest))
        self.assertEqual(loaded_capture.settings, settings)
        self.assertTrue(loaded_result.validation.valid)
        self.assertEqual(loaded_result.binding.source_indices.shape, (len(vertices), 4))

    def test_capture_hash_includes_solver_settings(self):
        vertices, faces = cube_mesh()
        source = SkinSource(0, "SCP", "S1", "ORIGINAL", "Cube", vertices, faces, np.ones(8))
        changed = SkinSolverSettings(collagen_depth_ratio=0.02)
        self.assertNotEqual(capture_hash("ROOT", (source,)), capture_hash("ROOT", (source,), changed))

    def test_status_round_trip_is_atomic_and_typed(self):
        status = SkinJobStatus("RUNNING", "Meshing", 0.75, "Extracting", ("low memory",))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "status.json"
            write_status(path, status)
            loaded = read_status(path)
            leftovers = tuple(Path(folder).glob(".*.tmp"))
        self.assertEqual((loaded, leftovers), (status, ()))

    def test_resolution_reduces_to_memory_limit(self):
        vertices, _faces = cube_mesh()
        limit = estimated_bytes(grid_spec(vertices, 160)[1])
        resolution, _spec = choose_resolution(vertices, limit, 220)
        self.assertEqual(resolution, 160)

    def test_solver_returns_valid_closed_shell(self):
        vertices, faces = cube_mesh()
        source = SkinSource(0, "SCP", "S1", "ORIGINAL", "Cube", vertices, faces, np.ones(8))
        capture = SkinCapture("ROOT", (source,), vertices.min(0), vertices.max(0), "hash", 1 / 32, 32)
        result = solve_capture(capture)
        self.assertTrue(result.validation.valid, result.validation.message)
        self.assertGreater(len(result.vertices), len(vertices))

    def test_solver_uses_authored_collagen_depth(self):
        vertices, faces = cube_mesh()
        source = SkinSource(0, "SCP", "S1", "ORIGINAL", "Cube", vertices, faces, np.ones(8))
        default = SkinSolverSettings()
        tight = SkinSolverSettings(default.minimum_offset_ratio, 0.0, default.collagen_core_ratio, default.collagen_falloff_ratio)
        captures = [
            SkinCapture("ROOT", (source,), vertices.min(0), vertices.max(0), name, 1 / 48, 48, settings=settings)
            for name, settings in (("default", default), ("tight", tight))
        ]
        full, reduced = (solve_capture(capture) for capture in captures)
        self.assertLess(reduced.statistics["volume"], full.statistics["volume"])
        self.assertEqual(full.statistics["settings"], settings_payload(default))

    def test_solver_observes_cancellation(self):
        vertices, faces = cube_mesh()
        source = SkinSource(0, "SCP", "S1", "ORIGINAL", "Cube", vertices, faces, np.ones(8))
        capture = SkinCapture("ROOT", (source,), vertices.min(0), vertices.max(0), "hash", 1 / 32, 32)
        with self.assertRaises(SkinCancelled):
            solve_capture(capture, cancelled=lambda: True)

    def test_scene_enforces_one_job_and_cancels_process(self):
        scene, process = FakeScene(), FakeProcess()
        with mock.patch.object(jobs, "_prepare_process", return_value=process):
            jobs.start_job(scene, "ROOT", "blender", lambda _path: None)
            with self.assertRaises(RuntimeError):
                jobs.start_job(scene, "ROOT", "blender", lambda _path: None)
            self.assertTrue(jobs.cancel_job(scene))
        self.assertTrue(process.terminated)
        jobs.finish_job(scene, False)
        jobs.shutdown_jobs()

    def test_startup_failure_retains_diagnostic_without_active_job(self):
        scene = FakeScene()
        with mock.patch.object(jobs, "_launch", side_effect=FileNotFoundError("missing worker")):
            with self.assertRaises(FileNotFoundError):
                jobs.start_job(scene, "ROOT", "blender", lambda _path: None)
        self.assertIsNone(jobs.active_job(scene))
        self.assertTrue(jobs.diagnostic_path(scene).endswith("job.log"))
        jobs.shutdown_jobs()

    def test_corrupt_result_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.npz"
            path.write_bytes(b"not an npz")
            with self.assertRaises((OSError, ValueError)):
                read_result(path)

    def test_worker_imports_job_manifest_writer(self):
        from workers import draft_skin_worker
        self.assertIs(draft_skin_worker.write_job, write_job)


if __name__ == "__main__":
    unittest.main()
