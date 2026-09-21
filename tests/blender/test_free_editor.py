from unittest.mock import patch
import bpy
from mathutils import Vector, Matrix
from _helpers import BlenderTestCase
from test_free_fibers import fixture
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.adapters import free_fiber_editor as editor
from anthroforge.core.visualization import free_fiber_runtime as runtime


def opened():
    owner, surface, item, points = fixture()
    service.configure_mode(owner, bpy.context.scene, item, 'FREE')
    objects = editor.open_edit(owner, bpy.context.scene, item)
    return owner, surface, item, points, objects


class FreeEditorTests(BlenderTestCase):
    def test_native_delete_cancels_editor_and_removes_source_and_mirrors(self):
        from anthroforge.core.visualization.delete_reconcile import reconcile_deleted_entities
        owner, _surface, item, _points, _objects = opened(); identity = item.id
        self.assertTrue(reconcile_deleted_entities(owner, bpy.context.scene, {('FIBER', identity, 'PROXY')}, explicit=True))
        self.assertFalse(any(o.get('af_free_editor_session') or o.get('af_fiber_id') == identity for o in bpy.data.objects))
        self.assertFalse(owner.af_vcp_system.fibers)

    def test_poly_noop_has_no_recapture_and_cancel_keeps_shape(self):
        owner, _surface, item, _points, _objects = opened(); previous = item.free_path_json
        with patch.object(service, 'commit', side_effect=AssertionError('Unexpected rewrite')):
            editor.apply(owner, bpy.context.scene, item)
        self.assertEqual(item.free_path_json, previous); self.assertFalse(editor.state(owner, item))
        objects = editor.open_edit(owner, bpy.context.scene, item); objects[0].data.splines[0].points[1].co.z += .2
        editor.cancel(owner, item); self.assertEqual(item.free_path_json, previous)
        self.assertFalse(any(o.get('af_free_editor_session') for o in bpy.data.objects))

    def test_editor_opens_current_deformed_geometry_and_recaptures(self):
        owner, surface, item, original, _objects = opened(); editor.cancel(owner, item)
        surface.location.z = .6; bpy.context.view_layer.update()
        objects = editor.open_edit(owner, bpy.context.scene, item)
        self.assertAlmostEqual(objects[0].data.splines[0].points[1].co.z, .9, places=5)
        objects[0].data.splines[0].points[1].co.z += .2; editor.apply(owner, bpy.context.scene, item)
        surface.location.z = 1.; bpy.context.view_layer.update()
        self.assertAlmostEqual(runtime.current(owner, bpy.context.scene, item)[1][1].z, 1.5, places=5)

    def test_stale_apply_and_explicit_rebase_preserve_draft(self):
        owner, surface, item, _points, objects = opened(); previous = item.free_path_json
        objects[0].data.splines[0].points[1].co.z += .15
        surface.location.z = .4; bpy.context.view_layer.update()
        with self.assertRaisesRegex(ValueError, 'STALE_FREE_EDIT'): editor.apply(owner, bpy.context.scene, item)
        self.assertEqual(previous, item.free_path_json)
        objects = editor.refresh(owner, bpy.context.scene, item, rebase=True)
        self.assertEqual(len(editor.state(owner, item)['recovery']), 1)
        self.assertAlmostEqual(objects[0].data.splines[0].points[1].co.z, .85, places=5)
        editor.apply(owner, bpy.context.scene, item)

    def test_explicit_bezier_and_transformed_editor(self):
        owner, _surface, item, _points, objects = opened()
        editor.convert_bezier(owner, item); spline = objects[0].data.splines[0]
        self.assertEqual(spline.type, 'BEZIER'); self.assertEqual(len(spline.bezier_points), 4)
        for point in spline.bezier_points: point.co.x -= 2.; point.handle_left.x -= 2.; point.handle_right.x -= 2.
        objects[0].location.x += 2.; item.free_sampling_resolution = 32
        editor.apply(owner, bpy.context.scene, item)
        self.assertEqual(len(runtime.current(owner, bpy.context.scene, item)[1]), 32)
        self.assertEqual(item.node_count, 64)

    def test_structural_endpoint_rejection_preserves_draft(self):
        owner, _surface, item, _points, objects = opened(); previous = item.free_path_json
        objects[0].data.splines[0].points[0].co.x += .2
        with self.assertRaisesRegex(ValueError, 'Structural'): editor.apply(owner, bpy.context.scene, item)
        self.assertEqual(item.free_path_json, previous); self.assertTrue(editor.state(owner, item))

    def test_recovery_and_editor_deletion_do_not_delete_native_fiber(self):
        from anthroforge.adapters import free_fiber_lifecycle as lifecycle
        owner, _surface, item, _points, objects = opened()
        objects[0].data.splines[0].points[1].co.z += .25; lifecycle.save()
        editor._remove_object(objects[0]); lifecycle.reconcile()
        session = editor.state(owner, item); self.assertTrue(session['stale'])
        self.assertAlmostEqual(editor.objects(session)[0].data.splines[0].points[1].co.z, .55, places=5)
        self.assertEqual(len(owner.af_vcp_system.fibers), 1)
