import json
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import numpy as np
from core.draft_skin.model import SkinResult
from core.topology.model import TopologyCapture, TopologyResult, SymmetryPlane
from core.topology.bindings import build_topology_skin_binding
from core.topology.validation import validate_topology
from core.warm_start.model import TopologyGuideBinding
from core.warm_start.strategy_model import TopologyUpdateContext, TopologyUpdateOptions, TopologyUpdateStopped
from core.warm_start.strategy_current import CurrentTopologyStrategy
from core.warm_start.strategy_pipeline import run_topology_strategy, require_rebuild_allowed
from core.warm_start.strategy_registry import resolve_strategy
from core.warm_start.topology_solver import reproject_topology, project_and_rebind_topology
from core.warm_start.job import WarmJobSpec, WARM_JOB_VERSION, read_job, write_job
from workers.topology_update import attempt_update, preflight
from workers import warm_update_array, warm_update_worker


def context(kind="warm"):
    skin = np.array(((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)), float)
    triangles = np.array(((0, 1, 2), (0, 2, 3)), np.int32)
    vertices = skin * .8 + (.1, .1, 0); quads = np.array(((0, 1, 2, 3),), np.int32)
    before = SkinResult(skin, triangles, np.ones(4))
    after = replace(before, vertices=skin + (0, 0, .05))
    binding = build_topology_skin_binding(vertices, skin, triangles)
    guide = TopologyGuideBinding(np.full(4, -1), np.full(4, -1), np.full(4, -1.0))
    old = TopologyResult(vertices, quads, np.zeros(1, np.int32), np.full(1, -1, np.int32),
                         {}, validate_topology(vertices, quads), skin_binding=binding, guide_binding=guide)
    capture = TopologyCapture("Root", after.vertices, triangles, (), skin.min(0), skin.max(0), "fixture")
    return TopologyUpdateContext(old, before, after, capture, kind)


class ModifiedStrategy:
    name, version = "test", 1

    def __init__(self, transform):
        self.transform = transform

    def solve(self, value):
        return self.transform(value, CurrentTopologyStrategy().solve(value))


def experimental(value, transform, **options):
    choice = TopologyUpdateOptions(strategy="test", failure_policy="STOP", **options)
    return run_topology_strategy(value, choice, ModifiedStrategy(transform))


def job(folder, **options):
    names = ("source.blend", "skin_result.npz", "topology_result.npz", "summary.json", "status.json",
             "job.log", "cancel.request", "request.json", "skin_capture.npz", "topology_capture.npz",
             "current_skin.npz", "current_topology.npz")
    return WarmJobSpec(WARM_JOB_VERSION, "Root", "AUTO", str(folder),
                      *(str(Path(folder) / name) for name in names), topology_update=options)


class TopologyStrategyTests(unittest.TestCase):
    def test_current_warm_is_identical_to_original_solver(self):
        value = context(); old, skin = value.topology, value.after_skin
        expected = reproject_topology(old.vertices, old.quads, skin.vertices, skin.triangles,
                                     old.skin_binding, old.guide_binding)[0]
        result = run_topology_strategy(value).result
        self.assertIsNotNone(result)
        np.testing.assert_array_equal(result.vertices, expected)
        np.testing.assert_array_equal(result.quads, old.quads)

    def test_current_rebind_is_identical_to_original_solver(self):
        value = context("rebuilt"); old, skin = value.topology, value.after_skin
        expected = project_and_rebind_topology(old.vertices, old.quads, skin.vertices, skin.triangles,
                                              old.face_regions, old.guide_indices, ())
        result = run_topology_strategy(value).result
        self.assertIsNotNone(result)
        np.testing.assert_array_equal(result.vertices, expected[0])
        np.testing.assert_array_equal(result.skin_binding.triangle_indices, expected[1].triangle_indices)

    def test_candidate_reordering_is_rejected(self):
        outcome = experimental(context(), lambda c, r: replace(r, vertex_ids=r.vertex_ids[::-1]))
        self.assertIsNone(outcome.result)
        self.assertIn("identities", outcome.diagnostics["message"])

    def test_vertex_count_change_is_rejected(self):
        outcome = experimental(context(), lambda c, r: replace(r, vertices=r.vertices[:-1]))
        self.assertIsNone(outcome.result)

    def test_nonfinite_positions_are_rejected(self):
        outcome = experimental(context(), lambda c, r: replace(r, vertices=r.vertices * np.nan))
        self.assertIsNone(outcome.result)

    def test_inverted_faces_are_warned_without_rebuild(self):
        outcome = experimental(context(), lambda c, r: replace(r, vertices=r.vertices[[0, 3, 2, 1]]))
        self.assertIsNotNone(outcome.result)
        self.assertIn("inverted", outcome.result.statistics["strategy_metrics"]["quality_warning"])

    def test_collapsed_face_is_rejected(self):
        outcome = experimental(context(), lambda c, r: replace(r, vertices=np.tile(r.vertices[0], (4, 1))))
        self.assertIsNone(outcome.result)

    def test_missing_binding_triangle_is_rejected(self):
        outcome = experimental(context(), lambda c, r: replace(r,
            skin_binding=replace(r.skin_binding, triangle_indices=np.full(4, 999))))
        self.assertIsNone(outcome.result)

    def test_surface_tolerance_is_shared_and_checks_actual_offset(self):
        def move(c, r):
            return replace(r, vertices=r.vertices + (0, 0, 1),
                           skin_binding=replace(r.skin_binding, offsets=np.ones(4)))
        outcome = experimental(context(), move, maximum_surface_error=.01)
        self.assertIsNotNone(outcome.result)
        self.assertIn("surface-fit", outcome.result.statistics["strategy_metrics"]["quality_warning"])

    def test_symmetry_is_checked_outside_strategy(self):
        value = context(); plane = SymmetryPlane(np.array((.5, 0, 0)), np.array((1., 0, 0)))
        value = replace(value, capture=replace(value.capture, plane=plane))
        outcome = experimental(value, lambda c, r: replace(r, vertices=r.vertices + (.1, 0, 0)))
        self.assertIsNotNone(outcome.result)
        self.assertIn("symmetry", outcome.result.statistics["strategy_metrics"]["quality_warning"])

    def test_inputs_and_bindings_remain_unchanged(self):
        value = context(); vertices = value.topology.vertices.copy()
        binding = value.topology.skin_binding.triangle_indices.copy()
        def mutate(c, r):
            c.topology.vertices[0] = 5
        outcome = experimental(value, mutate)
        self.assertIsNone(outcome.result)
        np.testing.assert_array_equal(value.topology.vertices, vertices)
        np.testing.assert_array_equal(value.topology.skin_binding.triangle_indices, binding)

    def test_both_snapshots_reach_strategy(self):
        received = []
        def inspect(c, r):
            received.append(c)
            return replace(r, deformation={"schema": 1, "kind": "test"})
        result = experimental(context(), inspect).result
        self.assertFalse(np.array_equal(received[0].before_skin.vertices, received[0].after_skin.vertices))
        self.assertEqual(result.statistics["update_deformation"]["schema"], 1)

    def test_unknown_strategy_is_not_silently_replaced(self):
        with self.assertRaisesRegex(ValueError, "unavailable"):
            run_topology_strategy(context(), {"strategy": "nonrigid_icp"})

    def test_version_mismatch_is_not_silently_replaced(self):
        with self.assertRaisesRegex(ValueError, "version"):
            run_topology_strategy(context(), {"version": 2})

    def test_experimental_module_resolves_explicit_export(self):
        strategy = ModifiedStrategy(lambda c, r: r)
        with mock.patch.dict(sys.modules, {"af_strategy_test": SimpleNamespace(STRATEGY=strategy)}):
            options = TopologyUpdateOptions("test", 1, "af_strategy_test", "STOP")
            self.assertIs(resolve_strategy(options), strategy)
            self.assertIsNotNone(run_topology_strategy(context(), options).result)

    def test_cancel_before_solve_and_before_result(self):
        for callback in (lambda: True, mock.Mock(side_effect=(False, True, True))):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                run_topology_strategy(replace(context(), cancelled=callback))

    def test_existing_quality_failure_does_not_block_strategy(self):
        value = context()
        old = replace(value.topology, validation=replace(value.topology.validation, valid=False))
        self.assertIsNotNone(run_topology_strategy(replace(value, topology=old)).result)

    def test_memory_preflight_rejects_before_strategy_runs(self):
        selected = mock.Mock(name="strategy", version=1)
        selected.name = "test"
        outcome = run_topology_strategy(replace(context(), memory_budget=1),
                                        TopologyUpdateOptions(strategy="test"), selected)
        self.assertIsNone(outcome.result)
        selected.solve.assert_not_called()
        self.assertIn("memory budget", outcome.diagnostics["message"])

    def test_unmarked_skin_connectivity_change_is_rejected(self):
        value = context()
        after = replace(value.after_skin, triangles=value.after_skin.triangles[::-1])
        self.assertIsNone(run_topology_strategy(replace(value, after_skin=after)).result)

    def test_stop_policy_blocks_classified_rebuild(self):
        with tempfile.TemporaryDirectory() as folder:
            spec = job(folder, failure_policy="STOP")
            with self.assertRaises(TopologyUpdateStopped):
                preflight(spec, SimpleNamespace(topology_rebuild=True))

    def test_stop_and_rebuild_policy_are_independent(self):
        diagnostics = {"message": "Rejected face", "status": "REJECTED"}
        require_rebuild_allowed({"failure_policy": "REBUILD"}, diagnostics)
        with self.assertRaisesRegex(TopologyUpdateStopped, "Rejected face"):
            require_rebuild_allowed({"failure_policy": "STOP"}, diagnostics)

    def test_rejected_worker_attempt_records_diagnostics_before_stop(self):
        value = context(); value.topology.vertices[0] = np.nan
        with tempfile.TemporaryDirectory() as folder:
            spec = job(folder, failure_policy="STOP")
            with self.assertRaises(TopologyUpdateStopped):
                attempt_update(spec, value.capture, value.after_skin, value.topology,
                               SimpleNamespace(topology_rebuild=False), "rebuilt", value.before_skin)
            report = json.loads((Path(folder) / "topology_strategy.json").read_text())
        self.assertEqual(report["status"], "REJECTED")

    def test_job_options_roundtrip_and_legacy_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            spec = job(folder, failure_policy="STOP", settings={})
            write_job(spec); loaded = read_job(Path(folder) / "job.json")
            self.assertEqual(loaded.topology_update["failure_policy"], "STOP")
            payload = asdict(spec); payload["version"] = 2; del payload["topology_update"]
            (Path(folder) / "job.json").write_text(json.dumps(payload))
            legacy = read_job(Path(folder) / "job.json")
        self.assertEqual(legacy.topology_update["strategy"], "current")
        self.assertEqual(legacy.topology_update["failure_policy"], "REBUILD")

    def test_rejection_preserves_backend_diagnostics(self):
        outcome = experimental(context(), lambda c, r: replace(r, accepted=False,
            message="Cannot resolve region", diagnostics={"failed_regions": [3, 8]}))
        self.assertEqual(outcome.diagnostics["solver"]["failed_regions"], [3, 8])

    def test_array_job_checkpoints_skin_before_topology_rejection(self):
        value = context(); old = replace(value.topology, vertices=value.topology.vertices * np.nan)
        inputs = (SimpleNamespace(sources=()), value.capture, value.before_skin, old)
        request = {"classification": "GEOMETRY_ONLY", "skin_rebuild": False, "topology_rebuild": False}
        with tempfile.TemporaryDirectory() as folder:
            spec = job(folder, failure_policy="STOP"); write_job(spec)
            Path(spec.request_path).write_text(json.dumps(request))
            with mock.patch.object(warm_update_array, "_read_inputs", return_value=inputs):
                with mock.patch.object(warm_update_array, "_solve_skin", return_value=(value.after_skin, "warm")):
                    with mock.patch.object(warm_update_array, "_write_outputs") as publish:
                        with self.assertRaises(TopologyUpdateStopped):
                            warm_update_array.run_array_job(folder)
            publish.assert_not_called()
            self.assertTrue(Path(spec.skin_result_path).exists())
            self.assertTrue(Path(spec.job_dir, "completed_stages.json").exists())

    def test_blender_worker_does_not_generate_after_stop_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            error = TopologyUpdateStopped({"message": "Rejected test"})
            with mock.patch.object(warm_update_worker, "_topology_object", return_value=object()):
                with mock.patch.object(warm_update_worker, "_try_warm_topology", side_effect=error):
                    with mock.patch.object(warm_update_worker, "_full_topology") as rebuild:
                        with self.assertRaises(TopologyUpdateStopped):
                            warm_update_worker._solve_topology(None, None, None,
                                SimpleNamespace(topology_rebuild=False), "rebuilt", job(folder, failure_policy="STOP"))
            rebuild.assert_not_called()

    def test_rebuild_policy_still_calls_generator_after_rejection(self):
        value = context(); old = replace(value.topology, vertices=value.topology.vertices * np.nan)
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(warm_update_array, "_full_topology", return_value=value.topology) as rebuild:
                result, kind = warm_update_array._solve_topology(job(folder), value.capture,
                    value.after_skin, old, SimpleNamespace(topology_rebuild=False), "rebuilt", value.before_skin)
            rebuild.assert_called_once()
        self.assertEqual(kind, "rebuilt")
