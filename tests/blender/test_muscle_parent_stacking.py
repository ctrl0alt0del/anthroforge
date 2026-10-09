"""Final stacking publications unblock only the affected downstream geometry."""
import bpy
from _helpers import BlenderTestCase
from _stacking_fixture import fixture
from test_muscle_stacking import refresh
from test_muscle_pairs import finish
from test_muscle_parent_fibers import arched_fiber
from anthroforge.core.vcp.surface_reference import key, from_object
from anthroforge.core.visualization.muscle_sync_helpers import resolve_muscle_surface
from anthroforge.core.visualization.surface_target_service import default_surface_target_service
from anthroforge.core.muscle_pairs import runtime


def child(owner, surface):
    import os
    from unittest.mock import patch
    from anthroforge.core.visualization.fiber_refinement import request_fiber_refinement, drain_fiber_refinements
    fiber, _points = arched_fiber(owner, surface, key(from_object(surface)))
    with patch.dict(os.environ, {'AF_FIBER_ENGINE': 'V3'}):
        result = request_fiber_refinement(owner, bpy.context.scene, fiber, quality='FINAL')
        assert result.ok, result.error
        drain_fiber_refinements()
    return fiber


class MuscleParentStackingTests(BlenderTestCase):
    def test_pending_stacking_is_barrier_and_final_surface_resumes_fiber(self):
        from anthroforge.core.vcp.fiber_node_attachment import capture_fiber_node_attachments
        from anthroforge.core.visualization.free_fiber_runtime import current
        from anthroforge.app.use_cases.free_fiber import configure_mode
        owner, _under, cover = fixture(); state = refresh(owner)
        self.assertEqual(state['stacking']['publication'], 'published')
        surface = resolve_muscle_surface(owner, cover.id, 'INFL', bpy.context.scene); ref = from_object(surface)
        fiber = child(owner, surface)
        configure_mode(owner, bpy.context.scene, fiber, 'FREE'); raw = fiber.node_attachments_json
        runtime.refresh(bpy.context.scene, owner, True)
        self.assertEqual(default_surface_target_service().resolve(owner, bpy.context.scene, ref).readiness, 'PENDING')
        finish()
        self.assertEqual(default_surface_target_service().resolve(owner, bpy.context.scene, ref).readiness, 'CURRENT')
        self.assertEqual(raw, fiber.node_attachments_json)
        self.assertTrue(current(owner, bpy.context.scene, fiber)[1])

    def test_stacking_feedback_is_rejected_before_support_commit(self):
        from anthroforge.app.use_cases.fiber_attachment import set_supports
        owner, under, cover = fixture(); refresh(owner)
        surface = next(s for s in owner.af_vcp_system.fiber_surfaces if s.id == under.fiber_surface_id)
        fiber = next(f for f in owner.af_vcp_system.fibers if f.id == surface.fiber_refs[0].fiber_id)
        target = key(from_object(resolve_muscle_surface(owner, cover.id, 'INFL', bpy.context.scene)))
        with self.assertRaisesRegex(ValueError, 'Cyclic'): set_supports(owner, bpy.context.scene, fiber, (target,))
        self.assertFalse(fiber.attachment_supports)
