"""Adversarial edit recovery and mode boundaries for native Free paths."""
from unittest.mock import patch
import bpy
from _helpers import BlenderTestCase, select_only
from test_free_editor import opened
from anthroforge.adapters import free_fiber_editor as editor, free_fiber_lifecycle as lifecycle
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.core.vcp import fiber_authority


class FreeLifecycleTests(BlenderTestCase):
    def test_direct_source_and_draft_selection_resolve_panel_without_tree_selection(self):
        from anthroforge.ui.panels.fiber_edit_panel import AF_PT_FiberEditPanel
        from anthroforge.app.queries.vcp import active_fiber_from_context
        owner, _surface, fiber, _points, objects = opened()
        owner.af_scp_system.active_scp_index = 0; owner.af_vcp_system.active_vcp_id = ''
        source = next(o for o in bpy.context.scene.objects if o.get('af_fiber_proxy'))
        for obj in (source, objects[0]):
            select_only(obj)
            with self.subTest(object=obj.name):
                self.assertTrue(AF_PT_FiberEditPanel.poll(bpy.context))
                self.assertEqual(active_fiber_from_context(bpy.context).id, fiber.id)

    def test_mode_change_is_blocked_until_draft_is_closed(self):
        owner, _surface, fiber, _points, objects = opened(); before = fiber.free_path_json
        objects[0].data.splines[0].points[1].co.z += .2
        with self.assertRaisesRegex(ValueError, 'EDIT_IN_PROGRESS'):
            service.configure_mode(owner, bpy.context.scene, fiber, 'CONTROLLED')
        self.assertEqual(fiber.behavior_mode, 'FREE'); self.assertEqual(fiber.free_path_json, before)
        self.assertTrue(editor.state(owner, fiber))

    def test_authority_change_rejects_apply_without_committed_writes(self):
        owner, _surface, fiber, _points, objects = opened(); before = fiber.free_path_json
        objects[0].data.splines[0].points[1].co.z += .2; fiber_authority.invalidate(fiber)
        with patch.object(service, 'commit', side_effect=AssertionError('Stale write')):
            with self.assertRaisesRegex(ValueError, 'STALE_FREE_EDIT'): editor.apply(owner, bpy.context.scene, fiber)
        self.assertEqual(fiber.free_path_json, before); self.assertTrue(editor.state(owner, fiber)['stale'])

    def test_root_transform_change_rejects_apply_without_recapture(self):
        owner, _surface, fiber, _points, _objects = opened(); before = fiber.node_attachments_json
        owner.location.x += .1; bpy.context.view_layer.update()
        with patch.object(service, 'commit', side_effect=AssertionError('Stale write')):
            with self.assertRaisesRegex(ValueError, 'STALE_FREE_EDIT'): editor.apply(owner, bpy.context.scene, fiber)
        self.assertEqual(fiber.node_attachments_json, before); self.assertTrue(editor.state(owner, fiber))

    def test_unsupported_spline_state_preserves_committed_path_and_draft(self):
        owner, _surface, fiber, _points, objects = opened(); before = fiber.free_path_json
        spline = objects[0].data.splines[0]; spline.use_cyclic_u = True
        with self.assertRaisesRegex(ValueError, 'cyclic'): editor.apply(owner, bpy.context.scene, fiber)
        spline.use_cyclic_u = False; objects[0].data.splines.new('POLY')
        with self.assertRaisesRegex(ValueError, 'exactly one'): editor.apply(owner, bpy.context.scene, fiber)
        self.assertEqual(fiber.free_path_json, before); self.assertTrue(editor.state(owner, fiber))
        editor.cancel(owner, fiber)
        self.assertFalse(any(o.get('af_free_editor_session') for o in bpy.data.objects))

    def test_refresh_keeps_old_draft_and_uses_current_deformation(self):
        owner, surface, fiber, _points, objects = opened()
        objects[0].data.splines[0].points[1].co.z += .2; surface.location.z = .4
        bpy.context.view_layer.update(); objects = editor.refresh(owner, bpy.context.scene, fiber)
        session = editor.state(owner, fiber)
        self.assertAlmostEqual(session['recovery'][0]['spans'][0]['values'][1][2], .5, places=5)
        self.assertAlmostEqual(objects[0].data.splines[0].points[1].co.z, .7, places=5)
        self.assertFalse(session['stale']); editor.apply(owner, bpy.context.scene, fiber)

    def test_unregister_reregister_recovers_raw_bezier_without_apply(self):
        owner, _surface, fiber, _points, objects = opened(); before = fiber.free_path_json
        editor.convert_bezier(owner, fiber); point = objects[0].data.splines[0].bezier_points[1]
        point.handle_right_type = 'FREE'; point.handle_right.z += .2; expected = list(point.handle_right)
        lifecycle.unregister()
        try:
            self.assertEqual(fiber.free_path_json, before)
            self.assertFalse(any(o.get('af_free_editor_session') for o in bpy.data.objects))
        finally: lifecycle.register()
        session = editor.state(owner, fiber); self.assertTrue(session['stale'])
        recovered = editor.objects(session)[0].data.splines[0].bezier_points[1]
        self.assertEqual(list(recovered.handle_right), expected); self.assertEqual(fiber.free_path_json, before)
