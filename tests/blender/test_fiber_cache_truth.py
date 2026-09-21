from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import bpy
from mathutils import Vector

ADDON_ROOT = Path(__file__).resolve().parents[2]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from anthroforge.core.vcp.fiber_collision import (
    _collider_stamp, clear_collider_generations, note_collider_updates)
from anthroforge.core.vcp.fiber_planner import PlannerAnchor
from anthroforge.core.vcp.fiber_progressive import (
    FiberLevelState, FiberSolveSession, _finish_cached_loop, _finish_session,
    publish_fiber_cache)
from anthroforge.core.vcp.fiber_solver import FiberSolver
from anthroforge.core.visualization import fiber_refinement


def _points(z=0.0):
    return [Vector((0.0, 0.0, z)), Vector((1.0, 0.0, z)), Vector((0.0, 1.0, z))]


def _fiber():
    return SimpleNamespace(id="F", use_warm_start=True, topology_mode="LOOP",
                           symmetry_mode="NONE", symmetry_axis="X", symmetry_origin=())


def _params(signature):
    return {"node_count": 3, "_cache_signature": signature, "margin": 0.0,
            "segment_collisions": True, "eps_pen": 1.0e-5}


def _context_signature(solver, fiber, scene_uid, root_uid):
    root, scene = SimpleNamespace(session_uid=root_uid), SimpleNamespace(session_uid=scene_uid)
    params = {"node_count": 3, "iterations": 4, "solver_version": 2}
    oracle = SimpleNamespace(colliders=lambda: ({"sid": "S", "stamp": (1,)},))
    return solver._solve_cache_signature(root, scene, fiber, (), params, oracle, "FINAL", True)


class FiberCacheTruthTests(unittest.TestCase):
    def tearDown(self):
        clear_collider_generations()

    def test_exact_loop_revalidates_and_reports_actual_residual(self):
        solver, fiber, signature = FiberSolver(), _fiber(), ("exact", 1)
        solver._store_loop_exact_result(fiber, signature, _points(), (True, 0.125, 0.004, 7))
        anchors = [PlannerAnchor(point) for point in _points()]
        with patch.object(solver, "_finish_cyclic_state",
                          return_value=(True, 0.125, 0.0004)) as validate:
            result = solver._solve_loop_nodes(fiber, anchors, None, _params(signature), _points())
        self.assertEqual((result[1], result[2], result[3], result[4]),
                         (True, 0.125, 0.0004, 7))
        validate.assert_called_once()

    def test_unsafe_exact_loop_falls_through_to_refinement(self):
        solver, fiber, signature = FiberSolver(), _fiber(), ("unsafe", 1)
        anchors = [PlannerAnchor(point) for point in _points()]
        solver._store_loop_exact_result(fiber, signature, _points(), (True, 0.1, 0.0, 2))
        with patch.object(solver, "_finish_cyclic_state", return_value=(False, 0.1, 0.2)), \
             patch.object(solver, "_active_colliders", return_value=[]), \
             patch.object(solver, "_run_cyclic_iterations", return_value=(True, 0.2, 0.0)) as refine:
            result = solver._solve_loop_nodes(fiber, anchors, None, _params(signature), _points())
        self.assertEqual((result[1], result[3], refine.call_count), (True, 0.0, 1))
        self.assertFalse(solver._loop_exact_results)

    def test_unsafe_progressive_hit_never_finishes(self):
        solver, fiber, signature = FiberSolver(), _fiber(), ("progressive-unsafe", 1)
        solver._store_loop_exact_result(fiber, signature, _points(), (True, 0.1, 0.0, 2))
        session = FiberSolveSession(solver, None, fiber, None, None, loop=True)
        session.params, session.anchors, session.oracle = _params(signature), [PlannerAnchor(p) for p in _points()], object()
        cached = solver._cached_loop_result(fiber, signature, 3)
        with patch.object(solver, "_finish_cyclic_state", return_value=(False, 0.1, 0.2)):
            finished = _finish_cached_loop(session, cached)
        self.assertEqual((finished, session.done), (False, False))
        self.assertFalse(solver._loop_exact_results)

    def test_warm_seed_is_not_an_exact_result(self):
        solver, fiber, signature = FiberSolver(), _fiber(), ("warm", 1)
        solver._store_warm_cache(fiber, _points(), signature)
        self.assertIsNone(solver._cached_loop_result(fiber, signature, 3))
        self.assertEqual(len(solver._warm_loop_nodes(fiber, 3, signature)), 3)

    def test_progressive_cache_waits_for_publication(self):
        solver, fiber, signature = FiberSolver(), _fiber(), ("accepted", 1)
        session = FiberSolveSession(solver, None, fiber, None, None, loop=True)
        session.params = _params(signature)
        session.level = FiberLevelState(_points(), set(), {}, session.params,
                                        _points(), [], None, None, converged=True)
        with patch.object(solver, "_store_status"), patch.object(solver, "_store_metrics"):
            _finish_session(session, True, False)
        self.assertFalse(solver._warm_cache or solver._loop_exact_results)
        with patch('anthroforge.core.vcp.fiber_authority.session_owned', return_value=True):
            publish_fiber_cache(session, session.result())
        self.assertTrue(solver._warm_cache and solver._loop_exact_results)

    def test_refinement_publishes_only_after_output_commit(self):
        fiber, result = object(), SimpleNamespace()
        job = SimpleNamespace(session=object(), output_committed=False)
        with patch.object(fiber_refinement, "_invalid_job_reason", return_value=None), \
             patch.object(fiber_refinement, "_authority_current", return_value=True), \
             patch.object(fiber_refinement, "_owned_job_data", return_value=(None, None, fiber)), \
             patch.object(fiber_refinement, "_store_result"), patch.object(fiber_refinement, "_commit_allowed", return_value=True), \
             patch.object(fiber_refinement, "_restore_previous_output"), patch.object(fiber_refinement, "_finish_pending_version"), \
             patch.object(fiber_refinement, "_detach_job"), patch.object(fiber_refinement, "_sync_final"), \
             patch.object(fiber_refinement, "publish_fiber_cache") as publish:
            fiber_refinement._finish_job(job, result)
            job.output_committed = True
            fiber_refinement._finish_job(job, result)
        publish.assert_called_once_with(job.session, result)

    def test_geometry_update_advances_collider_stamp(self):
        mesh = bpy.data.meshes.new("FiberCacheTruthMesh")
        mesh.from_pydata(_points(), (), ((0, 1, 2),))
        obj = bpy.data.objects.new("FiberCacheTruthObject", mesh)
        bpy.context.scene.collection.objects.link(obj)
        before = _collider_stamp(obj)
        update = SimpleNamespace(id=mesh, is_updated_geometry=True, is_updated_transform=False)
        note_collider_updates(SimpleNamespace(updates=(update,)))
        self.assertNotEqual(before, _collider_stamp(obj))
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)

    def test_signature_includes_quality_and_collider_state(self):
        solver, fiber = FiberSolver(), _fiber()
        root, scene = SimpleNamespace(session_uid=2), SimpleNamespace(session_uid=1)
        params = {"node_count": 3, "iterations": 4, "solver_version": 2}
        first = SimpleNamespace(colliders=lambda: ({"sid": "S", "stamp": (1,)},))
        second = SimpleNamespace(colliders=lambda: ({"sid": "S", "stamp": (2,)},))
        a = solver._solve_cache_signature(root, scene, fiber, (), params, first, "FINAL", True)
        b = solver._solve_cache_signature(root, scene, fiber, (), params, second, "FINAL", True)
        c = solver._solve_cache_signature(root, scene, fiber, (), params, first, "INTERACTIVE", True)
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)

    def test_duplicate_ids_across_contexts_do_not_share_warm_cache(self):
        solver, first, second = FiberSolver(), _fiber(), _fiber()
        first_sig = _context_signature(solver, first, 1, 2)
        second_sig = _context_signature(solver, second, 3, 4)
        solver._store_warm_cache(first, _points(0.0), first_sig)
        solver._store_warm_cache(second, _points(1.0), second_sig)
        first_points = solver._warm_start_nodes(first, 3, first_sig)
        second_points = solver._warm_start_nodes(second, 3, second_sig)
        self.assertNotEqual(first_sig, second_sig)
        self.assertTrue(all(point.z == 0.0 for point in first_points))
        self.assertTrue(all(point.z == 1.0 for point in second_points))
        self.assertIsNone(solver._warm_start_nodes(first, 3, second_sig))

    def test_duplicate_ids_across_contexts_do_not_share_exact_cache(self):
        solver, first, second = FiberSolver(), _fiber(), _fiber()
        first_sig = _context_signature(solver, first, 1, 2)
        second_sig = _context_signature(solver, second, 3, 4)
        solver._store_loop_exact_result(first, first_sig, _points(0.0), (True, 0.0, 0.0, 1))
        solver._store_loop_exact_result(second, second_sig, _points(1.0), (True, 0.0, 0.0, 1))
        first_points = solver._cached_loop_result(first, first_sig, 3)[0]
        second_points = solver._cached_loop_result(second, second_sig, 3)[0]
        self.assertTrue(all(point.z == 0.0 for point in first_points))
        self.assertTrue(all(point.z == 1.0 for point in second_points))
        self.assertIsNone(solver._cached_loop_result(first, second_sig, 3))


if __name__ == "__main__":
    unittest.main()
