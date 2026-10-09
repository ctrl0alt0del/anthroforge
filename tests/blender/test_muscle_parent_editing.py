"""Explicit recovery, shared identities and update gates on muscle parents."""
import bpy
from mathutils import Vector
from _helpers import BlenderTestCase, find_flagged, root
from test_muscle_parent_fibers import parent_fixture, arched_fiber, tissue_chain
from anthroforge.app.use_cases import fiber_attachment, free_fiber
from anthroforge.core.visualization.free_fiber_runtime import current
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates


def free_fixture():
    owner, muscle, surface, parent = parent_fixture()
    fiber, points = arched_fiber(owner, surface, parent)
    free_fiber.configure_mode(owner, bpy.context.scene, fiber, 'FREE')
    return owner, muscle, surface, fiber, points


def change_topology(surface):
    vertices = [tuple(v.co) for v in surface.data.vertices] + [(100., 100., 100.)]
    faces = [tuple(p.vertices) for p in surface.data.polygons]
    surface.data.clear_geometry(); surface.data.from_pydata(vertices, [], faces)
    surface.data.update(); bpy.context.view_layer.update()


class MuscleParentEditingTests(BlenderTestCase):
    def test_explicit_rebind_recovers_topology_without_changing_path(self):
        owner, muscle, surface, fiber, points = free_fixture()
        raw = fiber.node_attachments_json; change_topology(surface)
        with self.assertRaises(ValueError): current(owner, bpy.context.scene, fiber)
        fiber_attachment.rebind_fiber(owner, bpy.context.scene, fiber)
        self.assertNotEqual(raw, fiber.node_attachments_json)
        for a, b in zip(points, current(owner, bpy.context.scene, fiber)[1]): self.assertLess((a-b).length, 1e-5)

    def test_failed_rebind_preserves_all_shared_bindings_and_path(self):
        from unittest.mock import patch
        owner, _muscle, _surface, fiber, _points = free_fixture()
        saved = fiber.a_attach_param, fiber.b_attach_param, fiber.node_attachments_json, fiber.free_path_json
        with patch.object(fiber_attachment.free_point_edit, 'apply_changed', side_effect=ValueError('Rejected geometry')):
            with self.assertRaisesRegex(ValueError, 'Rejected geometry'): fiber_attachment.rebind_fiber(owner, bpy.context.scene, fiber)
        self.assertEqual(saved, (fiber.a_attach_param, fiber.b_attach_param, fiber.node_attachments_json, fiber.free_path_json))

    def test_disabled_attachments_resume_retained_bindings(self):
        from anthroforge.core.visualization.muscle_fiber_attachment import apply_batch
        from anthroforge.core.visualization.fiber_sync import register_fiber_sync
        owner, muscle, surface, fiber, points = free_fixture()
        proxy = find_flagged('af_fiber_proxy', fiber.id, 'af_fiber_id'); saved = proxy['af_fiber_points_world']
        raw = fiber.node_attachments_json; bpy.context.scene.af_attachments_enabled = False
        with suppress_vcp_prop_updates(): muscle.inflation_max_value += .05
        apply_batch(register_fiber_sync(), owner, bpy.context.scene, (fiber,))
        self.assertEqual(saved, proxy['af_fiber_points_world'])
        bpy.context.scene.af_attachments_enabled = True
        apply_batch(register_fiber_sync(), owner, bpy.context.scene, (fiber,))
        self.assertEqual(raw, fiber.node_attachments_json)
        self.assertGreater(max((b-a).length for a, b in zip(points, current(owner, bpy.context.scene, fiber)[1])), 1e-4)

    def test_manual_tissue_preserves_last_geometry_and_marks_stale(self):
        from anthroforge.core.visualization.sync_runner import sync_from_dirty_hints
        owner, muscle, tissue, _surface = tissue_chain('LAYER')
        proxy = find_flagged('af_soft_tissue_proxy', tissue.id, 'af_soft_tissue_id')
        before = tuple(tuple(v.co) for v in proxy.data.vertices)
        with suppress_vcp_prop_updates(): tissue.auto_recompute = False; muscle.inflation_max_value += .05
        sync_from_dirty_hints(owner, bpy.context.scene, {'MUSCLE': {muscle.id}}, source='test', event_type='UPDATE')
        self.assertEqual(before, tuple(tuple(v.co) for v in proxy.data.vertices))
        self.assertEqual(proxy.get('af_soft_tissue_output_state'), 'STALE')

    def test_external_missing_parent_blocks_branch_without_rebinding(self):
        from anthroforge.core.visualization.sync_runner import sync_from_dirty_hints
        owner, muscle, tissue, surface = tissue_chain('LAYER'); identity = muscle.id
        raw = tuple(f.node_attachments_json for f in owner.af_vcp_system.fibers if f.behavior_mode == 'FREE')
        with suppress_vcp_prop_updates(): owner.af_vcp_system.muscles.remove(0)
        bpy.data.objects.remove(surface, do_unlink=True)
        sync_from_dirty_hints(owner, bpy.context.scene, {'MUSCLE': {identity}}, source='test', event_type='UPDATE')
        self.assertEqual(raw, tuple(f.node_attachments_json for f in owner.af_vcp_system.fibers if f.behavior_mode == 'FREE'))
        proxy = find_flagged('af_soft_tissue_proxy', tissue.id, 'af_soft_tissue_id')
        self.assertEqual(proxy.get('af_soft_tissue_output_state'), 'STALE')
