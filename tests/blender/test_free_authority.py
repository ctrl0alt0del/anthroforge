from unittest.mock import patch
import bpy
from _helpers import BlenderTestCase
from test_free_fibers import fixture
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.core.visualization import fiber_refinement as refinement
from anthroforge.core.vcp.fiber_engine import FiberTermination
from anthroforge.core.vcp.runtime_state import fiber_recompute_status
from anthroforge.core.visualization.fiber_sync_helpers import persisted_fiber_points


class FreeAuthorityTests(BlenderTestCase):
    def test_failed_controlled_transition_retains_attachment_deformation_at_free_sample_count(self):
        from anthroforge.core.vcp.runtime_state import set_fiber_recompute_status
        from anthroforge.core.visualization.fiber_node_attachment_runtime import _apply_fiber_node_attachments_serial
        from anthroforge.core.vcp.free_path import fiber_geometry_point_count
        owner, surface, fiber, points = fixture(); service.configure_mode(owner, bpy.context.scene, fiber, 'FREE')
        def fail(*args, **kwargs):
            set_fiber_recompute_status(fiber, 'INFEASIBLE')
            return refinement.RefinementRequest(False, 'Injected solver failure')
        with patch.object(refinement, 'request_fiber_refinement', side_effect=fail): service.configure_mode(owner, bpy.context.scene, fiber, 'CONTROLLED')
        self.assertEqual(fiber.node_count, 64); self.assertEqual(fiber_geometry_point_count(fiber), 4)
        surface.location.z = .2; bpy.context.view_layer.update()
        _apply_fiber_node_attachments_serial(owner, bpy.context.scene, {fiber.id})
        self.assertEqual(fiber_recompute_status(fiber), 'INFEASIBLE')
        actual = persisted_fiber_points(bpy.context.scene, owner.name, fiber.id)
        self.assertLess(max(abs(p.z - q.z - .2) for p, q in zip(actual, points)), 1e-5)

    def test_late_progress_restore_status_migration_and_cache_after_both_transitions(self):
        owner, _surface, fiber, points = fixture()
        job = refinement.request_fiber_refinement(owner, bpy.context.scene, fiber).job
        self.assertIsNotNone(job); result = job.session.result()
        service.configure_mode(owner, bpy.context.scene, fiber, 'FREE')
        self._late(owner, fiber, job, result, points)
        with patch.object(refinement, 'request_fiber_refinement'):
            service.configure_mode(owner, bpy.context.scene, fiber, 'CONTROLLED')
        self._late(owner, fiber, job, result, points)

    def _late(self, owner, fiber, job, result, points):
        status, version = fiber_recompute_status(fiber), fiber.solver_version
        with patch.object(job.session.solver, '_store_warm_cache', side_effect=AssertionError('late cache')):
            refinement._apply_progress(job, result, known_valid=True); refinement._finish_refined_job(job, result)
            refinement._restore_previous_output(job); refinement._restore_job_status(job, fiber, True)
            refinement._publish_commit_identity(job, result); refinement._finish_pending_version(job, True)
            refinement._publish_result_cache(job, result); refinement._terminate_job(job, FiberTermination.CANCELLED, True)
            from anthroforge.core.vcp.fiber_progressive import publish_fiber_cache
            publish_fiber_cache(job.session, result)
        self.assertEqual(fiber_recompute_status(fiber), status); self.assertEqual(fiber.solver_version, version)
        self.assertEqual(persisted_fiber_points(bpy.context.scene, owner.name, fiber.id), points)

    def test_all_fiber_aware_solver_entrypoints_reject_free(self):
        from anthroforge.core.vcp.fiber_solver import FiberSolver
        from anthroforge.core.vcp.fiber_progressive import begin_fiber_solve
        from anthroforge.core.vcp.fiber_v2_runtime import begin_v2_runtime, begin_v3_runtime
        owner, _surface, fiber, _points = fixture(); service.configure_mode(owner, bpy.context.scene, fiber, 'FREE')
        solver = FiberSolver()
        with self.assertRaisesRegex(ValueError, 'FREE_SOLVER_FORBIDDEN'):
            solver.solve_points(owner, fiber, bpy.context.scene, None)
        for method in (begin_fiber_solve, begin_v2_runtime, begin_v3_runtime):
            with self.assertRaisesRegex(ValueError, 'FREE_SOLVER_FORBIDDEN'):
                method(solver, owner, fiber, bpy.context.scene, None, 'FINAL', None)
