"""Failure, transform, source-goal and transactional integration acceptance."""
import os
from unittest.mock import patch
import bpy
import numpy as np
from mathutils import Matrix, Vector
from _helpers import BlenderTestCase, find_flagged, scp_with_object, select_only
from test_muscle_parent_editing import free_fixture
from test_muscle_parent_fibers import parent_fixture, arched_fiber, tissue_chain
from test_muscle_parent_updates import collision_fixture
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.visualization.muscle_fiber_attachment import apply_batch, resolve_batch
from anthroforge.core.visualization.free_fiber_runtime import current
from anthroforge.core.visualization.fiber_refinement import drain_fiber_refinements
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates


def tissue_result(owner, tissue):
    from anthroforge.core.visualization.soft_tissue_sync import _evaluate_generic_tissue, register_soft_tissue_sync
    return _evaluate_generic_tissue(register_soft_tissue_sync(), owner, bpy.context.scene, tissue, 'NONE')


class MuscleParentAcceptanceTests(BlenderTestCase):
    def test_native_and_binding_resolution_agree_after_rotation_and_scale(self):
        owner, _muscle, surface, fiber, _points = free_fixture(); raw = fiber.node_attachments_json
        surface.matrix_world = Matrix.Translation((.2, -.1, .3)) @ Matrix.Rotation(.4, 4, 'Y') @ Matrix.Diagonal((1.2, .8, 1.1, 1)) @ surface.matrix_world
        bpy.context.view_layer.update(); rows, errors = resolve_batch(owner, bpy.context.scene, (fiber,))
        self.assertFalse(errors); expected = current(owner, bpy.context.scene, fiber)[1]
        np.testing.assert_allclose(rows[fiber.id], expected, atol=1e-5)
        self.assertEqual(raw, fiber.node_attachments_json)

    def test_impossible_route_retains_previous_output_and_reason(self):
        from anthroforge.core.vcp.runtime_state import fiber_invalid_reason
        owner, fiber, _surface, points = collision_fixture()
        bpy.ops.mesh.primitive_cube_add(size=.3, location=points[0]+Vector((0,0,.125)))
        scp_with_object(owner, 'Enclosed structural anchor', bpy.context.object)
        proxy = find_flagged('af_fiber_proxy', fiber.id, 'af_fiber_id'); old = proxy['af_fiber_points_world']
        with patch.dict(os.environ, {'AF_FIBER_ENGINE': 'V3'}):
            apply_batch(register_fiber_sync(), owner, bpy.context.scene, (fiber,)); drain_fiber_refinements()
        self.assertEqual(proxy.get('af_fiber_output_state'), 'STALE')
        self.assertEqual(old, proxy['af_fiber_points_world']); self.assertTrue(fiber_invalid_reason(fiber))

    def test_superseded_native_reroute_publishes_latest_parent_generation(self):
        from anthroforge.core.vcp.fiber_support_validation import validate
        from anthroforge.core.visualization.fiber_sync_helpers import persisted_fiber_points
        owner, fiber, surface, _points = collision_fixture(); anchors = fiber.a_attach_param, fiber.b_attach_param
        with patch.dict(os.environ, {'AF_FIBER_ENGINE': 'V3'}):
            apply_batch(register_fiber_sync(), owner, bpy.context.scene, (fiber,))
            for vertex in surface.data.vertices: vertex.co.z += .015
            from anthroforge.core.visualization.surface_publication import changed
            changed(surface)
            surface.data.update(); bpy.context.view_layer.update()
            apply_batch(register_fiber_sync(), owner, bpy.context.scene, (fiber,)); drain_fiber_refinements()
        self.assertEqual(anchors, (fiber.a_attach_param, fiber.b_attach_param))
        points = persisted_fiber_points(bpy.context.scene, owner.name, fiber.id)
        self.assertTrue(validate(owner, bpy.context.scene, fiber, points))

    def test_source_fixed_offsets_include_backing(self):
        from anthroforge.core.vcp.soft_tissue_source_goals import source_goals
        owner, _muscle, tissue, _surface = tissue_chain('POUCH')
        with suppress_vcp_prop_updates():
            tissue.attachments.clear(); row = tissue.attachments.add(); row.mode = 'FIXED'; row.mask_attribute = 'BACKING'; row.normal_offset = .01
        result = tissue_result(owner, tissue)
        for mode, index, goal, _strength in source_goals(tissue, result.rest, result.sample):
            if mode == 'FIXED': self.assertLess((Vector(result.final.vertices[index])-Vector(goal)).length, 1e-5)

    def test_source_soft_strength_changes_layer_response(self):
        owner, _muscle, tissue, _surface = tissue_chain('LAYER')
        with suppress_vcp_prop_updates():
            row = tissue.attachments.add(); row.mode = 'SOFT'; row.mask_attribute = 'ALL'; row.strength = 0
        loose = tissue_result(owner, tissue)
        with suppress_vcp_prop_updates(): row.strength = .9
        tethered = tissue_result(owner, tissue)
        self.assertGreater(np.max(np.abs(np.asarray(loose.final.vertices)-tethered.final.vertices)), 1e-5)
        self.assertLess(tethered.final.max_displacement, loose.final.max_displacement)

    def test_source_rim_from_muscle_fiber_has_no_second_attachment(self):
        owner, _muscle, _surface, fiber, _points = free_fixture()
        select_only(find_flagged('af_fiber_proxy', fiber.id, 'af_fiber_id'))
        bpy.context.scene.af_new_soft_tissue_preset = 'RIM'; bpy.context.scene.af_new_soft_tissue_target_obj = None
        self.assertEqual(bpy.ops.af.add_soft_tissue_vcp(), {'FINISHED'})
        tissue = owner.af_vcp_system.soft_tissues[-1]
        self.assertEqual((tissue.constraint_reference, tissue.attachment_target_type), ('SOURCE', 'NONE'))
        self.assertTrue(tissue_result(owner, tissue).final.vertices)

    def test_transaction_failure_restores_tissue_configuration_and_geometry(self):
        from anthroforge.adapters.free_fiber_transaction import run
        owner, _muscle, tissue, _surface = tissue_chain('LAYER')
        proxy = find_flagged('af_soft_tissue_proxy', tissue.id, 'af_soft_tissue_id')
        before = tissue.inflation_amount, tuple(tuple(v.co) for v in proxy.data.vertices)
        def fail():
            with suppress_vcp_prop_updates(): tissue.inflation_amount = .7
            proxy.data.vertices[0].co.z += .2
            raise ValueError('Injected failure after downstream publication')
        with self.assertRaises(ValueError): run(owner, bpy.context.scene, fail)
        self.assertEqual(before, (tissue.inflation_amount, tuple(tuple(v.co) for v in proxy.data.vertices)))
