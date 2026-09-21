import bpy
import numpy as np
from mathutils import Vector
from _helpers import BlenderTestCase, capture_world_attachment
from test_free_fibers import fixture
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.adapters import free_fiber_editor as editor
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization import free_fiber_runtime as runtime
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.app.use_cases.fiber_surface_create import _new_surface, _assign_refs
from anthroforge.core.visualization.fiber_surface_sync import evaluate_surface_record


def loop_fixture():
    owner, surface, fiber, _points = fixture(); scp = fiber.a_parent_id
    points = [Vector((.1, .1, 0)), Vector((.6, .1, 0)), Vector((.1, .6, 0))]
    with suppress_vcp_prop_updates():
        fiber.topology_mode = 'LOOP'
        for point in points:
            row = fiber.loop_anchors.add(); row.parent_id = scp; row.attach_param = capture_world_attachment(owner, scp, point)
    register_fiber_sync().apply_points(owner, bpy.context.scene, fiber, points)
    service.configure_mode(owner, bpy.context.scene, fiber, 'FREE')
    return owner, surface, fiber, points


class FreeLoopTests(BlenderTestCase):
    def test_native_loop_editor_closure_exact_patch_and_explicit_bezier(self):
        owner, _surface, fiber, points = loop_fixture(); objects = editor.open_edit(owner, bpy.context.scene, fiber)
        self.assertEqual(len(objects), 3); editor.apply(owner, bpy.context.scene, fiber)
        with suppress_vcp_prop_updates():
            surface = _new_surface(owner.af_vcp_system, 'Free loop', 'LOOP_PATCH', False, False)
            _assign_refs(surface, [fiber.id]); surface.patch_resolution = 2
        result = evaluate_surface_record(owner, bpy.context.scene, surface)
        self.assertTrue(result.faces); self.assertEqual(len(runtime.current(owner, bpy.context.scene, fiber)[1]), 3)
        editor.open_edit(owner, bpy.context.scene, fiber); editor.convert_bezier(owner, fiber)
        fiber.free_sampling_resolution = 32; editor.apply(owner, bpy.context.scene, fiber)
        actual = runtime.current(owner, bpy.context.scene, fiber)[1]
        self.assertEqual(len(actual), 32); self.assertGreater((actual[-1] - actual[0]).length, 0)

    def test_source_and_mirror_remain_visible_normal_curves(self):
        owner, _surface, fiber, _points = loop_fixture()
        with suppress_vcp_prop_updates(): owner.af_scp_system.scps[0].mirror_enabled = True
        runtime.update(owner, bpy.context.scene, fiber)
        register_fiber_sync().sync_root_to_scene(owner, bpy.context.scene)
        curves = [o for o in bpy.context.scene.objects if o.get('af_fiber_id') == fiber.id and o.get('af_fiber_proxy')]
        self.assertEqual(len(curves), 2)
        self.assertEqual(sum(bool(o.get('af_fiber_mirror_proxy')) for o in curves), 1)
        self.assertTrue(all(o.type == 'CURVE' and not o.hide_get() and not o.hide_viewport for o in curves))
