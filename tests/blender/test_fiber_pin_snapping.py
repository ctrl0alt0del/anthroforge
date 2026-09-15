"""Production pin fallback: same-owner, collision clear, shared UI/authoring policy."""
from unittest.mock import patch
import bpy
import numpy as np
from mathutils import Vector
from _helpers import BlenderTestCase, root, scp_with_object, empty_object
from anthroforge.core.vcp import attachment_backend as backend, fiber_pin_snapping as snapping
from anthroforge.core.vcp.fiber_pin_snap_validation import triangle_components
from anthroforge.core.vcp.fiber_pin_snap_search import FiberPinSnapSearch
from anthroforge.core.visualization import fiber_sync_runtime as sync_runtime, fiber_view_capture
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates


def cube(root_obj, location=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=2, location=location)
    obj = bpy.context.object; scp = scp_with_object(root_obj, obj.name, obj)
    return obj, scp.id


class FiberPinSnappingTests(BlenderTestCase):
    def setUp(self):
        super().setUp(); self.root = root(); self.obj, self.owner = cube(self.root)
        self.scene = bpy.context.scene

    def snap(self, point=(.2, .1, 1.), offset=0., radius=.002):
        runtime = backend.attachment_runtime(self.scene)
        raw = backend.capture_attachment_from_world(self.root, self.scene, self.owner, Vector(point), runtime)
        return snapping.qualify_attachment(self.root, self.scene, self.owner, raw, runtime, radius, offset)

    def test_valid_raw_is_preserved_without_fallback_search(self):
        raw = backend.capture_attachment_from_world(self.root, self.scene, self.owner, Vector((.2, .1, 1)))
        with patch.object(FiberPinSnapSearch, 'seeds', side_effect=AssertionError('unnecessary search')):
            result = self.snap()
        self.assertEqual(result.raw, raw); self.assertEqual(result.mode, 'NEAREST')

    def test_offset_and_radius_are_used_in_qualification(self):
        cube(self.root, (0, 0, 2.01))
        self.assertEqual(self.snap(radius=.002).mode, 'NEAREST')
        self.assertNotEqual(self.snap(radius=.02).mode, 'NEAREST')
        result = self.snap(offset=.02)
        runtime = backend.attachment_runtime(self.scene)
        frame = backend.resolve_surface_frame(self.obj, result.raw, runtime)
        np.testing.assert_allclose(result.point, frame['point_world'] + .02*frame['normal_world'], atol=1e-7)

    def test_no_exit_activates_fallback_even_when_point_is_clear(self):
        from anthroforge.core.vcp import fiber_pin_snap_validation as validation
        ordinary = validation.has_exit
        with patch.object(validation, 'has_exit', side_effect=lambda s, r: False if np.linalg.norm(np.asarray(r['point'])-s.origin)<.01 else ordinary(s, r)):
            result = self.snap()
        self.assertTrue(result.valid); self.assertEqual(result.reason, 'NO_LOCAL_PIN_EXIT')
        self.assertGreaterEqual(result.displacement, .00999)

    def test_overlapping_parts_of_one_owner_are_not_exempt(self):
        other, _owner = cube(self.root, (0, 0, 1.5))
        vertices = [tuple(v.co) for v in self.obj.data.vertices]
        vertices += [tuple(other.matrix_world @ v.co) for v in other.data.vertices]
        faces = [tuple(p.vertices) for p in self.obj.data.polygons]
        faces += [tuple(i+8 for i in p.vertices) for p in other.data.polygons]
        self.obj.data.clear_geometry(); self.obj.data.from_pydata(vertices, [], faces); self.obj.data.update()
        bpy.data.objects.remove(other, do_unlink=True); bpy.context.view_layer.update()
        result = self.snap()
        self.assertTrue(result.valid); self.assertEqual(result.reason, 'BURIED_OWNER_SURFACE')
        self.assertGreater(result.displacement, 0.)

    def test_native_failure_does_not_return_unsafe_nearest(self):
        with patch.object(snapping, 'snap_request', side_effect=RuntimeError('missing backend')):
            result = self.snap()
        self.assertFalse(result.valid); self.assertIn('BACKEND_UNAVAILABLE', result.reason)

    def test_world_is_shared_within_one_authoring_operation(self):
        runtime = backend.attachment_runtime(self.scene)
        raw = backend.capture_attachment_from_world(self.root, self.scene, self.owner, Vector((.2, .1, 1)))
        with patch.object(snapping, 'snap_request', wraps=snapping.snap_request) as capture:
            for _index in range(2): snapping.qualify_attachment(self.root, self.scene, self.owner, raw, runtime)
        self.assertEqual(capture.call_count, 1)

    def test_geometry_change_is_seen_by_next_snap_operation(self):
        self.assertEqual(self.snap().mode, 'NEAREST')
        cube(self.root, (0, 0, 1.5)); bpy.context.view_layer.update()
        self.assertEqual(self.snap().reason, 'ANCHOR_BLOCKED')

    def test_endpoint_edit_and_shared_service_agree(self):
        cube(self.root, (0, 0, 1.5)); expected = self.snap()
        fiber, handle = self.handle('A'); handle.location = (.2, .1, 1.)
        self.update(handle)
        self.assertEqual(fiber.a_attach_param, expected.raw)
        self.assertEqual(fiber.a_parent_id, self.owner)
        np.testing.assert_allclose(handle.location, expected.surface, atol=1e-7)

    def test_failed_edit_restores_binding_and_handle(self):
        fiber, handle = self.handle('A'); previous = fiber.a_attach_param
        old = backend.resolve_attachment_world(self.root, self.scene, self.owner, previous)
        enclosing, _owner = cube(self.root); enclosing.scale = (2, 2, 2)
        handle.location = (.2, .1, 1.); self.update(handle)
        self.assertEqual(fiber.a_attach_param, previous)
        np.testing.assert_allclose(handle.location, old, atol=1e-7)

    def test_touch_and_loop_edits_use_same_fallback(self):
        cube(self.root, (0, 0, 1.5)); fiber, handle = self.handle('A')
        touch = fiber.mid_touches.add(); touch.parent_id = self.owner; touch.normal_offset = .02
        touch.attach_param = fiber.a_attach_param; handle['af_fiber_touch_index'] = 0
        anchor = fiber.loop_anchors.add(); anchor.parent_id = self.owner; anchor.attach_param = fiber.a_attach_param
        handle['af_fiber_loop_anchor_index'] = 0
        ray = (Vector((.2, .1, 1.4)), Vector((0, 0, -1)))
        for item, method, offset in ((touch, sync_runtime._update_touch_handle, .02), (anchor, sync_runtime._update_loop_anchor_handle, 0.)):
            expected = self.snap(offset=offset); handle.location = (.2, .1, 1.)
            with patch.object(fiber_view_capture, 'view_ray_for_world_point', return_value=ray):
                method(register_fiber_sync(), self.root, self.scene, handle, set(), bpy.context.evaluated_depsgraph_get())
            self.assertEqual(item.attach_param, expected.raw); self.assertEqual(item.parent_id, self.owner)
            np.testing.assert_allclose(handle.location, expected.surface, atol=1e-7)
        self.assertAlmostEqual(touch.normal_offset, .02)

    def test_quick_fiber_preview_follows_qualified_point(self):
        from anthroforge.app.use_cases import action_library_quick_fiber as quick
        cube(self.root, (0, 0, 1.5)); surface = Vector((.2, .1, 1.))
        runtime = backend.attachment_runtime(self.scene)
        expected = snapping.capture_attachment_from_world(self.root, self.scene, self.owner, surface, runtime)
        with patch.object(quick, 'root_for_context', return_value=self.root):
            point, error = quick.capture_quick_fiber_point(bpy.context, (self.owner, surface, surface+Vector((0, 0, .01))))
        self.assertEqual(error, ''); self.assertEqual(point.attach_param, expected)
        np.testing.assert_allclose(point.attach_world, runtime['pin_snap_last_result'].surface, atol=1e-7)
        np.testing.assert_allclose(point.visual_world-point.attach_world, (0, 0, .01), atol=1e-7)

    def test_snap_does_not_start_planner_or_solver(self):
        from anthroforge.core.vcp.v2 import planner
        from anthroforge.core.vcp.v3 import production
        cube(self.root, (0, 0, 1.5))
        with patch.object(planner, 'plan_reference_v43', side_effect=AssertionError('planner')), patch.object(
                production, 'solve_v3', side_effect=AssertionError('solver')):
            self.assertTrue(self.snap().valid)

    def test_component_order_is_deterministic(self):
        self.assertEqual(triangle_components(((0, 1, 2), (4, 5, 6), (2, 3, 0))), ((0, 2), (1,)))

    def test_failed_selected_pin_cannot_be_silently_omitted(self):
        from anthroforge.app.use_cases import fiber_tools, fiber_create
        specs, error = fiber_tools._complete_touch_selection(((self.owner, 'raw'),), 2)
        self.assertFalse(specs); self.assertTrue(error)
        with patch.object(fiber_create, '_selected_mesh_indices', return_value=(0, 1, 2, 3)), patch.object(
                fiber_create, '_mesh_specs', return_value=((self.owner, 'raw'),)*3):
            specs, error = fiber_create._mesh_loop_specs(bpy.context, self.root)
        self.assertIsNone(specs); self.assertTrue(error)

    def handle(self, endpoint):
        with suppress_vcp_prop_updates():
            fiber = self.root.af_vcp_system.fibers.add(); fiber.id = 'FIBER_1'
            fiber.a_parent_id = fiber.b_parent_id = self.owner
            fiber.a_attach_param = backend.capture_attachment_from_world(self.root, self.scene, self.owner, Vector((.2, .1, -1)))
            fiber.b_attach_param = fiber.a_attach_param
        handle = empty_object('Pin'); handle['af_fiber_id'] = fiber.id; handle['af_fiber_endpoint'] = endpoint
        return fiber, handle

    def update(self, handle):
        ray = (Vector((.2, .1, 1.4)), Vector((0, 0, -1)))
        with patch.object(fiber_view_capture, 'view_ray_for_world_point', return_value=ray):
            return sync_runtime._update_endpoint_handle(register_fiber_sync(), self.root, self.scene,
                                                        handle, set(), bpy.context.evaluated_depsgraph_get())
