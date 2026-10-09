"""Deformation-driven safety checks, native rerouting and publication barriers."""
import os
from unittest.mock import patch
import bpy
from mathutils import Vector
from _helpers import BlenderTestCase, scp_with_object, find_flagged
from test_muscle_parent_fibers import parent_fixture, arched_fiber
from anthroforge.core.vcp.fiber_node_attachment import capture_fiber_node_attachments
from anthroforge.core.visualization.muscle_fiber_attachment import apply_batch
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.visualization.fiber_refinement import drain_fiber_refinements


def collision_fixture(free=False):
    owner, muscle, surface, parent = parent_fixture(); fiber, points = arched_fiber(owner, surface, parent)
    capture_fiber_node_attachments(owner, bpy.context.scene, fiber, points)
    if free:
        from anthroforge.app.use_cases.free_fiber import configure_mode
        configure_mode(owner, bpy.context.scene, fiber, 'FREE')
    bpy.ops.mesh.primitive_cube_add(size=.06, location=points[3] + Vector((0, 0, .125)))
    obstacle = bpy.context.object; scp_with_object(owner, 'Deformation obstruction', obstacle)
    for vertex in surface.data.vertices: vertex.co.z += .125
    surface.data.update(); bpy.context.view_layer.update()
    return owner, fiber, surface, points


class MuscleParentUpdateTests(BlenderTestCase):
    def test_collision_after_parent_deformation_reroutes_controlled(self):
        from anthroforge.core.vcp.runtime_state import fiber_invalid_reason
        from anthroforge.core.vcp.fiber_support_validation import validate
        from anthroforge.core.visualization.fiber_sync_helpers import persisted_fiber_points
        owner, fiber, _surface, _before = collision_fixture()
        anchors = fiber.a_attach_param, fiber.b_attach_param
        with patch.dict(os.environ, {'AF_FIBER_ENGINE': 'V3'}):
            apply_batch(register_fiber_sync(), owner, bpy.context.scene, (fiber,)); drain_fiber_refinements()
        proxy = find_flagged('af_fiber_proxy', fiber.id, 'af_fiber_id')
        self.assertEqual(proxy.get('af_fiber_output_state'), 'CURRENT', fiber_invalid_reason(fiber))
        self.assertEqual(anchors, (fiber.a_attach_param, fiber.b_attach_param))
        self.assertTrue(validate(owner, bpy.context.scene, fiber, persisted_fiber_points(bpy.context.scene, owner.name, fiber.id)))

    def test_free_collision_preserves_authored_geometry_and_binding(self):
        from anthroforge.core.visualization import fiber_refinement
        owner, fiber, _surface, _before = collision_fixture(True)
        raw = fiber.free_path_json, fiber.node_attachments_json
        proxy = find_flagged('af_fiber_proxy', fiber.id, 'af_fiber_id'); committed = proxy['af_fiber_points_world']
        with patch.object(fiber_refinement, 'request_fiber_refinement', side_effect=AssertionError('Free reroute')):
            apply_batch(register_fiber_sync(), owner, bpy.context.scene, (fiber,))
        self.assertEqual(proxy.get('af_fiber_output_state'), 'STALE')
        self.assertEqual(raw, (fiber.free_path_json, fiber.node_attachments_json))
        self.assertEqual(committed, proxy['af_fiber_points_world'])

    def test_failed_reroute_is_not_requeued_without_new_geometry(self):
        from anthroforge.core.visualization import fiber_refinement
        owner, fiber, _surface, _before = collision_fixture()
        failed = fiber_refinement.RefinementRequest(False, 'No feasible route')
        with patch.object(fiber_refinement, 'request_fiber_refinement', return_value=failed) as submit:
            for _ in range(2): apply_batch(register_fiber_sync(), owner, bpy.context.scene, (fiber,))
        self.assertEqual(submit.call_count, 1)
