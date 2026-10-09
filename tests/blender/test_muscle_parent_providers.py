"""Shared provider contract: identities, frames, invalidation and support edges."""
import json
import bpy
from mathutils import Vector
from _helpers import BlenderTestCase
from test_muscle_parent_fibers import parent_fixture, mirrored_surface, arched_fiber
from anthroforge.core.vcp import attachment_backend as bindings
from anthroforge.core.vcp.surface_reference import key, reference, from_object
from anthroforge.core.visualization.surface_target_service import default_surface_target_service


class MuscleParentProviderTests(BlenderTestCase):
    def test_mirrored_frames_follow_each_axis_and_offset_plane(self):
        from anthroforge.core.vcp.fiber_instance import MirroredFiber
        from anthroforge.core.visualization.mirror_rules import mirror_matrix
        from anthroforge.core.visualization.muscle_fiber_attachment import resolve_batch
        from anthroforge.core.vcp.fiber_node_attachment import capture_fiber_node_attachments
        owner, muscle, surface, parent = parent_fixture(); fiber, points = arched_fiber(owner, surface, parent)
        self.assertTrue(capture_fiber_node_attachments(owner, bpy.context.scene, fiber, points).ok)
        mirror = mirrored_surface(owner, muscle, surface)
        for vertex in mirror.data.vertices: vertex.co.z -= .25
        for axis in ('X','Y','Z'):
            transform = mirror_matrix(axis, (.3, -.2, .4)); mirror.matrix_world = transform @ surface.matrix_world
            mirror.data.update(); bpy.context.view_layer.update()
            rows, errors = resolve_batch(owner, bpy.context.scene, (MirroredFiber(fiber),))
            self.assertFalse(errors, errors)
            self.assertLess(max((actual-transform@source).length for source, actual in zip(points, rows[fiber.id])), 1e-5)

    def test_shared_scp_and_muscle_frame_identity_and_topology_contract(self):
        owner, muscle, outer, parent = parent_fixture(); mirror = mirrored_surface(owner, muscle, outer)
        targets = [owner.af_scp_system.scps[0].id, parent, key(from_object(mirror)), key(dict(type='MUSCLE',id=muscle.id,surface='MUSCLE_BASE'))]
        for target in targets:
            with self.subTest(target=target): self.assert_surface_contract(owner, target)

    def assert_surface_contract(self, owner, target):
        resolved = default_surface_target_service().resolve(owner, bpy.context.scene, reference(target))
        self.assertEqual(resolved.readiness, 'CURRENT'); obj = resolved.mesh_object
        query = obj.matrix_world @ obj.data.vertices[0].co
        raw = bindings.capture_attachment_from_world(owner, bpy.context.scene, target, query)
        runtime = bindings.attachment_runtime(bpy.context.scene); frame = bindings.resolve_surface_frame(obj, raw, runtime)
        self.assertEqual(json.loads(raw)['target'], json.loads(bindings.capture_surface_param(obj, query, runtime))['target'])
        self.assertLess((frame['point_world']-query).length, 1e-5)
        basis = frame['basis_world']; self.assertAlmostEqual(abs(basis.determinant()), 1., places=5)
        identity = key(from_object(obj)); obj.name += '_renamed'; self.assertEqual(identity, key(from_object(obj)))
        self.assertTrue(json.loads(raw)['topology_signature'])

    def test_zero_weight_explicit_support_is_still_a_dependency(self):
        from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
        from anthroforge.core.deps.surface_dependencies import consumers
        owner, muscle, surface, parent = parent_fixture(); fiber, _points = arched_fiber(owner, surface, parent)
        with suppress_vcp_prop_updates():
            support = owner.af_vcp_system.muscles.add(); support.id = 'MUSCLE_EXTRA'
            fiber.attachment_supports.add().target_id = key(dict(type='MUSCLE', id=support.id))
        self.assertIn(('FIBER', fiber.id), consumers(owner, 'MUSCLE', 'MUSCLE_EXTRA'))

    def test_rejected_native_publication_is_an_actionable_stale_result(self):
        import os
        from unittest.mock import patch
        from anthroforge.core.visualization.fiber_refinement import request_fiber_refinement, drain_fiber_refinements
        from anthroforge.core.vcp.runtime_state import fiber_invalid_reason
        from anthroforge.core.visualization import fiber_attachment_commit
        owner, _muscle, surface, parent = parent_fixture(); fiber, _points = arched_fiber(owner, surface, parent)
        with patch.dict(os.environ, {'AF_FIBER_ENGINE': 'V3'}), patch.object(fiber_attachment_commit, 'apply', side_effect=ValueError('Retained binding changed')):
            request_fiber_refinement(owner, bpy.context.scene, fiber); drain_fiber_refinements()
        self.assertIn('Retained binding changed', fiber_invalid_reason(fiber))
