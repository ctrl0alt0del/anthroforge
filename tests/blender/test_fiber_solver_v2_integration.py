from pathlib import Path
import json
import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bpy
import numpy as np
from mathutils import Vector

BLENDER_TEST_ROOT = Path(__file__).resolve().parent
TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(BLENDER_TEST_ROOT), str(TEST_ROOT), str(ADDON_ROOT.parent)):
    if value not in sys.path:
        sys.path.insert(0, value)

from anthroforge.core.vcp.fiber_progressive import _can_finish_direct
from anthroforge.core.vcp.fiber_solver import FiberSolver
from anthroforge.core.vcp.v2 import (V2Diagnostics, V2PlannerDiagnostics, V2PlannerMode,
                                     V2PlannerResult, V2Result, V2Termination)
from anthroforge.core.vcp.v2.collision import V2BackendStatus
from anthroforge.core.vcp.fiber_solver_v2 import (
    CYCLIC,
    OPEN,
    StaticFiberSettings,
    clear_factor_cache,
    factor_cache_stats,
    solve_static_fiber,
)
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.visualization.fiber_sync_helpers import cached_fiber_points, mark_fiber_output_stale
from anthroforge.core.visualization.fiber_refinement import drain_fiber_refinements, request_fiber_refinement
from anthroforge.core.visualization import sync_runner
from anthroforge.core.vcp.runtime_state import fiber_recompute_status
from anthroforge.core.visualization.muscle_sync_runtime import collect_fiber_points
from anthroforge.ui.panels.fiber_edit_panel import _STATUS_LABELS
from _helpers import BlenderTestCase, find_flagged, mesh_object, root, scp_with_object


class _ClearOracle:
    margin = clearance = 0.0

    def active_colliders_for_polyline(self, _points, padding=0.0):
        return ()

    def push_out_point(self, point, colliders=None):
        return point.copy(), 0.0


class _FiberStub(SimpleNamespace):
    def get(self, key, default=None):
        return self.pending.get(key, default)


def _nodes(cyclic=False):
    count = 8
    divisor = count if cyclic else count - 1
    return [Vector((i / divisor, 0.2 * np.sin(i), 0.1 * np.cos(2 * i))) for i in range(count)]


def _params(version, cyclic=False):
    return {"shorten_strength": 0.03, "bend_strength": 0.0002,
            "margin": 0.0, "segment_collisions": version >= 2,
            "solver_version": version, "endpoint_owners": ("", "")}


def _run_iteration(nodes, version, cyclic=False):
    solver, oracle = FiberSolver(), _ClearOracle()
    pins = {0: nodes[0].copy(), len(nodes) - 1: nodes[-1].copy()}
    flags = {0, len(nodes) - 1} if cyclic else [i in pins for i in range(len(nodes))]
    previous = [point.copy() for point in nodes]
    method = solver._cyclic_iteration if cyclic else solver._solver_iteration
    method(nodes, previous, flags, pins, oracle, (), _params(version, cyclic), 0)
    return pins


class FiberSolverV2IntegrationTests(unittest.TestCase):
    def test_open_v2_iteration_matches_global_core_and_exact_pins(self):
        nodes = _nodes(); seed = [point.copy() for point in nodes]
        pins = _run_iteration(nodes, 2)
        settings = StaticFiberSettings(0.03, 0.0002, 1.0, OPEN)
        expected = solve_static_fiber(seed, pins, settings).points
        np.testing.assert_allclose(nodes, expected, atol=1.0e-12)
        self.assertEqual((nodes[0], nodes[-1]), (pins[0], pins[len(nodes) - 1]))

    def test_cyclic_v2_iteration_uses_cyclic_global_core(self):
        nodes = _nodes(True); seed = [point.copy() for point in nodes]
        pins = _run_iteration(nodes, 2, True)
        settings = StaticFiberSettings(0.03, 0.0002, 1.0, CYCLIC)
        expected = solve_static_fiber(seed, pins, settings).points
        np.testing.assert_allclose(nodes, expected, atol=1.0e-12)

    def test_v1_iteration_does_not_call_v2_core(self):
        nodes = _nodes()
        with patch("anthroforge.core.vcp.fiber_solver.solve_static_fiber") as solve:
            _run_iteration(nodes, 1)
        solve.assert_not_called()

    def test_legacy_params_ignore_pending_engine_selection(self):
        fiber = _FiberStub(node_count=8, iterations_interactive=1, iterations_bake=1,
                           stretch_stiffness=0.1, bend_stiffness=0.01,
                           use_segment_collisions=False, solver_version=1,
                           collision_radius=0.0, pending={"af_pending_solver_version": 2})
        params = FiberSolver()._runtime_params(fiber, False)
        self.assertEqual((params["solver_version"], params["segment_collisions"]), (1, False))

    def test_legacy_params_ignore_committed_engine_provenance(self):
        fiber = _FiberStub(node_count=8, iterations_interactive=1, iterations_bake=1,
                           stretch_stiffness=0.1, bend_stiffness=0.01,
                           use_segment_collisions=False, solver_version=2,
                           collision_radius=0.0, pending={})
        params = FiberSolver()._runtime_params(fiber, False)
        self.assertEqual((params["solver_version"], params["segment_collisions"]), (1, False))

    def test_v1_keeps_segment_collision_toggle(self):
        fiber = _FiberStub(node_count=8, iterations_interactive=1, iterations_bake=1,
                           stretch_stiffness=0.1, bend_stiffness=0.01,
                           use_segment_collisions=False, solver_version=1,
                           collision_radius=0.0, pending={})
        params = FiberSolver()._runtime_params(fiber, False)
        self.assertEqual((params["solver_version"], params["segment_collisions"]), (1, False))

    def test_solver_cache_clear_also_clears_v2_factors(self):
        clear_factor_cache(); nodes = _nodes(); pins = {0: nodes[0], 7: nodes[7]}
        solve_static_fiber(nodes, pins, StaticFiberSettings())
        self.assertGreater(factor_cache_stats()["entries"], 0)
        FiberSolver().clear_cache("F")
        self.assertEqual(factor_cache_stats()["entries"], 0)

    def test_progressive_direct_shortcut_is_disabled_only_for_v2(self):
        solver = FiberSolver()
        v2 = SimpleNamespace(solver=solver, params={"solver_version": 2})
        self.assertFalse(_can_finish_direct(v2))
        v1 = _direct_session(solver)
        self.assertTrue(_can_finish_direct(v1))

class FiberSolverV2WorkflowTests(BlenderTestCase):
    def test_v2_planner_preview_uses_validated_planner_not_blocked_solver(self):
        root_obj, fiber = _legacy_fiber_setup(); package = _planner_package(24)
        proxy = _fiber_proxy(fiber); persisted = proxy.get("af_fiber_points_world")
        with patch.dict(os.environ, {"AF_FIBER_ENGINE": "V2", "AF_FIBER_DEFER_MS": "0"}):
            with patch("anthroforge.core.vcp.fiber_v2_runtime.begin_v2", return_value=_PackageSession(package)):
                fiber.preview_planner_route = True
                while sync_runner._PENDING:
                    sync_runner._flush_pending()
                self.assertTrue(drain_fiber_refinements())
        self.assertEqual((fiber_recompute_status(fiber), proxy.get("af_fiber_display_mode")),
                         ("PLANNER_PREVIEW", "PLANNER_PREVIEW"))
        self.assertEqual((len(proxy.data.splines[0].points), proxy.get("af_fiber_points_world")),
                         (24, persisted))

    def test_v2_terminal_statuses_have_ui_labels(self):
        expected = {"UNKNOWN", "BLOCKED", "STALLED", "BUDGET_EXHAUSTED", "UNSAFE_OUTPUT"}
        self.assertTrue(expected.issubset(_STATUS_LABELS))

    def test_synchronous_api_drains_selected_v2_session(self):
        root_obj, fiber = _v2_fiber_setup(); package = _stalled_package(24)
        solver = FiberSolver()
        with patch.dict(os.environ, {"AF_FIBER_ENGINE": "V2"}):
            with patch("anthroforge.core.vcp.fiber_v2_runtime.begin_v2", return_value=_PackageSession(package)) as solve:
                points = solver.solve_points(root_obj, fiber, bpy.context.scene,
                                             bpy.context.evaluated_depsgraph_get())
        self.assertEqual((solve.call_count, len(points)), (1, 24))

    def test_v2_sync_produces_exact_count_and_endpoint_pins(self):
        root_obj, fiber = _v2_fiber_setup()
        sync = register_fiber_sync(); sync.clear_solver_cache(fiber.id)
        package = _stalled_package(24, V2Termination.CONVERGED)
        with patch.dict(os.environ, {"AF_FIBER_ENGINE": "V2"}):
            with patch("anthroforge.core.vcp.fiber_v2_runtime.begin_v2", return_value=_PackageSession(package)):
                sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene, bake=False)
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        points = [Vector(row) for row in json.loads(proxy["af_fiber_points_world"])]
        self.assertEqual(len(points), 24)
        self.assertLess(points[0].length, 1.0e-9)
        self.assertLess((points[-1] - Vector((2.0, 0.0, 0.0))).length, 1.0e-9)

    def test_explicit_recompute_migrates_and_restore_reinstates_legacy(self):
        root_obj, fiber = _legacy_fiber_setup()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        original = json.loads(proxy["af_fiber_points_world"])
        with patch.dict(os.environ, {"AF_FIBER_ENGINE": "V2"}):
            with patch("anthroforge.core.visualization.fiber_refinement._commit_allowed", return_value=True):
                with patch("anthroforge.core.visualization.fiber_refinement._finish_job", _finish_as_converged):
                    self.assertEqual(bpy.ops.af.recompute_fiber(fiber_id=fiber.id), {"FINISHED"})
                    self.assertTrue(drain_fiber_refinements())
        self.assertEqual((fiber.solver_version, json.loads(fiber.legacy_points_json)), (2, original))
        self.assertEqual(proxy.get("af_fiber_output_state"), "CURRENT")
        self.assertEqual(bpy.ops.af.restore_legacy_fiber(fiber_id=fiber.id), {"FINISHED"})
        self.assertEqual((fiber.solver_version, json.loads(proxy["af_fiber_points_world"])), (1, original))
        self.assertEqual(proxy.get("af_fiber_output_engine"), "V1")

    def test_failed_migration_restores_persisted_shape_and_version(self):
        root_obj, fiber = _legacy_fiber_setup()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        original = proxy["af_fiber_points_world"]
        with patch.dict(os.environ, {"AF_FIBER_ENGINE": "V2"}):
            with patch("anthroforge.core.visualization.fiber_refinement._commit_allowed", return_value=False):
                self.assertEqual(bpy.ops.af.recompute_fiber(fiber_id=fiber.id), {"FINISHED"})
                self.assertTrue(drain_fiber_refinements())
        self.assertEqual((fiber.solver_version, proxy["af_fiber_points_world"]), (1, original))
        self.assertEqual(proxy.get("af_fiber_output_state"), "STALE")

    def test_stale_output_is_visible_but_rejected_by_consumers(self):
        root_obj, fiber = _legacy_fiber_setup()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        mark_fiber_output_stale(bpy.context.scene, root_obj.name, fiber.id)
        self.assertTrue(proxy.data.splines)
        self.assertIsNone(cached_fiber_points(bpy.context.scene, root_obj.name, fiber.id))
        self.assertIsNone(collect_fiber_points(root_obj, bpy.context.scene, (fiber,)))

    def test_validated_stalled_runtime_result_commits_as_current(self):
        root_obj, fiber = _v2_fiber_setup(); package = _stalled_package(24)
        with patch.dict(os.environ, {"AF_FIBER_ENGINE": "V2"}):
            with patch("anthroforge.core.vcp.fiber_v2_runtime.begin_v2", return_value=_PackageSession(package)):
                request_fiber_refinement(root_obj, bpy.context.scene, fiber, True, "INTERACTIVE")
                self.assertTrue(drain_fiber_refinements())
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        self.assertEqual((proxy.get("af_fiber_output_state"), fiber_recompute_status(fiber)),
                         ("CURRENT", "STALLED"))

    def test_validated_budget_result_commits_with_truthful_status(self):
        root_obj, fiber = _v2_fiber_setup()
        package = _stalled_package(24, V2Termination.BUDGET_EXHAUSTED)
        _commit_v2(self, root_obj, fiber, package)
        proxy = _fiber_proxy(fiber)
        self.assertEqual((proxy.get("af_fiber_output_state"), fiber_recompute_status(fiber)),
                         ("CURRENT", "BUDGET_EXHAUSTED"))

    def test_validated_blocked_result_is_only_failed_preview(self):
        root_obj, fiber = _legacy_fiber_setup(); proxy = _fiber_proxy(fiber)
        before = (proxy["af_fiber_points_world"], proxy.get("af_fiber_output_generation"))
        package = _stalled_package(24, V2Termination.BLOCKED)
        _commit_v2(self, root_obj, fiber, package, "INTERACTIVE")
        proxy = _fiber_proxy(fiber)
        self.assertEqual((proxy["af_fiber_points_world"],
                          proxy.get("af_fiber_output_generation")), before)
        self.assertEqual((fiber.solver_version, proxy.get("af_fiber_output_state")), (1, "STALE"))
        self.assertEqual((proxy.get("af_fiber_display_mode"), fiber_recompute_status(fiber)),
                         ("FAILED_PREVIEW", "BLOCKED"))

    def test_missing_backend_retains_last_good_without_v1_fallback(self):
        root_obj, fiber = _legacy_fiber_setup(); proxy = _fiber_proxy(fiber)
        before = (proxy["af_fiber_points_world"], proxy.get("af_fiber_output_generation"))
        unavailable = V2BackendStatus(False, "", "missing test backend")
        with patch.dict(os.environ, {"AF_FIBER_ENGINE": "V2"}):
            with patch("anthroforge.core.vcp.fiber_v2_runtime.collision_backend_status", return_value=unavailable):
                request = request_fiber_refinement(root_obj, bpy.context.scene, fiber, True)
        self.assertFalse(request.ok)
        self.assertEqual((fiber.solver_version, proxy.get("af_fiber_output_engine")), (1, "V1"))
        self.assertEqual((proxy["af_fiber_points_world"], proxy.get("af_fiber_output_generation")), before)
        self.assertEqual((proxy.get("af_fiber_output_state"), fiber_recompute_status(fiber)),
                         ("CURRENT", "BACKEND_UNAVAILABLE"))

    def test_invalid_engine_configuration_retains_last_good(self):
        root_obj, fiber = _legacy_fiber_setup(); proxy = _fiber_proxy(fiber)
        before = (proxy["af_fiber_points_world"], proxy.get("af_fiber_output_generation"))
        with patch.dict(os.environ, {"AF_FIBER_ENGINE": "AUTO"}):
            request = request_fiber_refinement(root_obj, bpy.context.scene, fiber, True)
        self.assertFalse(request.ok)
        self.assertEqual((fiber.solver_version, proxy.get("af_fiber_output_state")), (1, "CURRENT"))
        self.assertEqual((proxy["af_fiber_points_world"], proxy.get("af_fiber_output_generation")), before)
        self.assertEqual(fiber_recompute_status(fiber), "INVALID_CONFIGURATION")

    def test_v2_to_v1_to_v2_updates_provenance_and_keeps_legacy(self):
        root_obj, fiber = _legacy_fiber_setup(); package = _stalled_package(fiber.node_count)
        legacy = _fiber_proxy(fiber)["af_fiber_points_world"]
        _commit_v2(self, root_obj, fiber, package)
        self.assertEqual((fiber.solver_version, _fiber_proxy(fiber).get("af_fiber_output_engine")), (2, "V2"))
        _commit_v1(self, root_obj, fiber)
        self.assertEqual((fiber.solver_version, _fiber_proxy(fiber).get("af_fiber_output_engine")), (1, "V1"))
        _commit_v2(self, root_obj, fiber, package)
        self.assertEqual((fiber.solver_version, _fiber_proxy(fiber).get("af_fiber_output_engine")), (2, "V2"))
        self.assertEqual(fiber.legacy_points_json, legacy)

    def test_v3_opt_in_uses_final_budget_and_commits_v3_provenance(self):
        root_obj, fiber = _legacy_fiber_setup(); captured = {}
        package = _v3_package(fiber.node_count)
        def factory(request, **values):
            captured.update(request=request, values=values)
            return _PackageSession(package)
        with patch.dict(os.environ, {"AF_FIBER_ENGINE": "V3"}):
            with patch("anthroforge.core.vcp.v3.production.begin_v3", side_effect=factory):
                request = request_fiber_refinement(root_obj, bpy.context.scene, fiber, True, "INTERACTIVE")
                self.assertTrue(request.ok); self.assertTrue(drain_fiber_refinements())
        proxy = _fiber_proxy(fiber)
        self.assertEqual((fiber.solver_version, proxy.get("af_fiber_output_engine")), (3, "V3"))
        self.assertEqual(captured["request"].settings.max_accepted_steps, fiber.iterations_bake)
        self.assertEqual(captured["values"]["checkpoint_steps"], fiber.iterations_interactive)


def _direct_session(solver):
    anchor = lambda x: SimpleNamespace(point=Vector((x, 0, 0)), owner_id="")
    oracle = SimpleNamespace(colliders=lambda: (), segment_visible=lambda *_args: True)
    return SimpleNamespace(solver=solver, params={"solver_version": 1}, mode="DIRECT",
                           guides=[], preview=[Vector(), Vector((1, 0, 0))],
                           anchors=[anchor(0), anchor(1)], oracle=oracle)


def _stalled_package(count, termination=V2Termination.STALLED):
    points = tuple((2.0 * index / (count - 1), 0.0, 0.0) for index in range(count))
    diagnostics = V2Diagnostics(fixed_point_residual=1.0e-5)
    result = V2Result("runtime-test", termination, points, diagnostics,
                      True, "DIRECT", "validated recovery", "test-pin-runtime")
    return SimpleNamespace(result=result, trace=SimpleNamespace(planner_ms=1.0))


def _v3_package(count):
    package = _stalled_package(count); result = package.result
    package.result = V2Result(result.request_signature, result.termination, result.points,
        result.diagnostics, result.validated, result.route_branch, result.message,
        "fiber-v3-production-4", result.backend_version)
    return package


def _planner_package(count):
    package = _stalled_package(count, V2Termination.BLOCKED)
    points = tuple((2.0 * index / (count - 1), .1, 0.0) for index in range(count))
    planner = V2PlannerResult(V2Termination.CONVERGED, V2PlannerMode.ROADMAP,
                              reference=points, corridor=points,
                              diagnostics=V2PlannerDiagnostics(planner_ms=1.0))
    return SimpleNamespace(result=package.result, trace=package.trace, planner=planner)


def _fiber_proxy(fiber):
    return find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")


class _PackageSession:
    def __init__(self, package):
        self.package, self.done = package, True

    @property
    def points(self):
        return self.package.result.points

    infeasible = False

    def step(self):
        return self.package


def _commit_v2(case, root_obj, fiber, package, quality="FINAL"):
    with patch.dict(os.environ, {"AF_FIBER_ENGINE": "V2"}):
        with patch("anthroforge.core.vcp.fiber_v2_runtime.begin_v2", return_value=_PackageSession(package)):
            request = request_fiber_refinement(root_obj, bpy.context.scene, fiber, True, quality)
            case.assertTrue(request.ok)
            case.assertTrue(drain_fiber_refinements())


def _commit_v1(case, root_obj, fiber):
    with patch.dict(os.environ, {"AF_FIBER_ENGINE": "V1"}):
        request = request_fiber_refinement(root_obj, bpy.context.scene, fiber, True)
        case.assertTrue(request.ok)
        case.assertTrue(drain_fiber_refinements())


def _v2_fiber_setup():
    root_obj = root()
    origin = scp_with_object(root_obj, "Origin", mesh_object("Origin"))
    insert = scp_with_object(root_obj, "Insert", mesh_object("Insert", (2.0, 0.0, 0.0)))
    bpy.context.scene.af_new_fiber_origin_obj = origin.geometry_object_ref
    bpy.context.scene.af_new_fiber_insertion_obj = insert.geometry_object_ref
    bpy.ops.af.add_fiber_vcp()
    fiber = root_obj.af_vcp_system.fibers[0]
    with suppress_vcp_prop_updates():
        fiber.solver_version, fiber.node_count = 2, 24
    return root_obj, fiber


def _legacy_fiber_setup():
    root_obj, fiber = _v2_fiber_setup()
    with suppress_vcp_prop_updates():
        fiber.solver_version = 1
    register_fiber_sync().clear_solver_cache(fiber.id)
    return root_obj, fiber


def _finish_as_converged(job, result=None):
    value = result or job.session.result()
    value.converged = True
    return _ORIGINAL_FINISH_JOB(job, value)


from anthroforge.core.visualization.fiber_refinement import _finish_job as _ORIGINAL_FINISH_JOB


if __name__ == "__main__":
    unittest.main(argv=[__file__])
