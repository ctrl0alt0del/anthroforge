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
from anthroforge.core.vcp.v2 import V2Diagnostics, V2Result, V2Termination
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
from anthroforge.core.vcp.runtime_state import fiber_recompute_status
from anthroforge.core.visualization.muscle_sync_runtime import collect_fiber_points
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

    def test_pending_v2_selects_v2_and_forces_segment_validation(self):
        fiber = _FiberStub(node_count=8, iterations_interactive=1, iterations_bake=1,
                           stretch_stiffness=0.1, bend_stiffness=0.01,
                           use_segment_collisions=False, solver_version=1,
                           collision_radius=0.0, pending={"af_pending_solver_version": 2})
        params = FiberSolver()._runtime_params(fiber, False)
        self.assertEqual((params["solver_version"], params["segment_collisions"]), (2, True))

    def test_persistent_v2_selects_v2_without_pending_marker(self):
        fiber = _FiberStub(node_count=8, iterations_interactive=1, iterations_bake=1,
                           stretch_stiffness=0.1, bend_stiffness=0.01,
                           use_segment_collisions=False, solver_version=2,
                           collision_radius=0.0, pending={})
        params = FiberSolver()._runtime_params(fiber, False)
        self.assertEqual((params["solver_version"], params["segment_collisions"]), (2, True))

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
    def test_v2_sync_produces_exact_count_and_endpoint_pins(self):
        root_obj, fiber = _v2_fiber_setup()
        sync = register_fiber_sync(); sync.clear_solver_cache(fiber.id)
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
        with patch.dict(os.environ, {"AF_FIBER_V2_ROLLOUT": "1"}):
            with patch("anthroforge.core.visualization.fiber_refinement._commit_allowed", return_value=True):
                with patch("anthroforge.core.visualization.fiber_refinement._finish_job", _finish_as_converged):
                    self.assertEqual(bpy.ops.af.recompute_fiber(fiber_id=fiber.id), {"FINISHED"})
                    self.assertTrue(drain_fiber_refinements())
        self.assertEqual((fiber.solver_version, json.loads(fiber.legacy_points_json)), (2, original))
        self.assertEqual(bpy.ops.af.restore_legacy_fiber(fiber_id=fiber.id), {"FINISHED"})
        self.assertEqual((fiber.solver_version, json.loads(proxy["af_fiber_points_world"])), (1, original))

    def test_failed_migration_restores_persisted_shape_and_version(self):
        root_obj, fiber = _legacy_fiber_setup()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        original = proxy["af_fiber_points_world"]
        with patch.dict(os.environ, {"AF_FIBER_V2_ROLLOUT": "1"}):
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
        with patch.dict(os.environ, {"AF_FIBER_V2_RUNTIME": "PIN_SMOOTHING"}):
            with patch("anthroforge.core.vcp.fiber_v2_runtime.solve_pin_smoothing", return_value=package):
                request_fiber_refinement(root_obj, bpy.context.scene, fiber, True, "INTERACTIVE")
                self.assertTrue(drain_fiber_refinements())
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        self.assertEqual((proxy.get("af_fiber_output_state"), fiber_recompute_status(fiber)),
                         ("CURRENT", "STALLED"))


def _direct_session(solver):
    anchor = lambda x: SimpleNamespace(point=Vector((x, 0, 0)), owner_id="")
    oracle = SimpleNamespace(colliders=lambda: (), segment_visible=lambda *_args: True)
    return SimpleNamespace(solver=solver, params={"solver_version": 1}, mode="DIRECT",
                           guides=[], preview=[Vector(), Vector((1, 0, 0))],
                           anchors=[anchor(0), anchor(1)], oracle=oracle)


def _stalled_package(count):
    points = tuple((2.0 * index / (count - 1), 0.0, 0.0) for index in range(count))
    diagnostics = V2Diagnostics(fixed_point_residual=1.0e-5)
    result = V2Result("runtime-test", V2Termination.STALLED, points, diagnostics,
                      True, "DIRECT", "validated recovery", "test-pin-runtime")
    return SimpleNamespace(result=result, trace=SimpleNamespace(planner_ms=1.0))


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
