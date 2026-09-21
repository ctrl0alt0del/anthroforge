from unittest.mock import patch
import bpy
from mathutils import Vector
from _helpers import BlenderTestCase, capture_world_attachment, fiber, mesh_object, root, scp_with_object
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.visualization.fiber_sync_helpers import persisted_fiber_points
from anthroforge.core.visualization import free_fiber_runtime as runtime
from anthroforge.core.vcp import free_path


def fixture():
    owner = root(); surface = mesh_object('FreeSurface'); scp = scp_with_object(owner, 'FreeSurface', surface)
    with suppress_vcp_prop_updates():
        item = fiber(owner, scp.id, scp.id)
        item.a_attach_param = capture_world_attachment(owner, scp.id, Vector((.1, .1, 0)))
        item.b_attach_param = capture_world_attachment(owner, scp.id, Vector((.7, .1, 0)))
    points = [Vector((.1, .1, 0)), Vector((.3, .2, .3)), Vector((.5, .1, .2)), Vector((.7, .1, 0))]
    register_fiber_sync().apply_points(owner, bpy.context.scene, item, points)
    return owner, surface, item, points


class FreeFiberTests(BlenderTestCase):
    def test_conversion_freezes_committed_not_preview_without_solver(self):
        owner, _surface, item, points = fixture()
        register_fiber_sync().apply_points(owner, bpy.context.scene, item, [p + Vector((0, 0, 2)) for p in points], commit=False)
        with patch('anthroforge.core.visualization.fiber_refinement.begin_fiber_solve', side_effect=AssertionError('solver')):
            service.configure_mode(owner, bpy.context.scene, item, 'FREE')
        self.assertEqual(item.node_count, 64); self.assertEqual(free_path.fiber_geometry_point_count(item), 4)
        self.assertEqual(points, persisted_fiber_points(bpy.context.scene, owner.name, item.id))

    def test_multiple_skeletal_changes_resolve_current_path(self):
        owner, surface, item, points = fixture(); service.configure_mode(owner, bpy.context.scene, item, 'FREE')
        for height in (.4, .8):
            surface.location.z = height; bpy.context.view_layer.update()
            ok, error, _proxy = runtime.update(owner, bpy.context.scene, item)
            self.assertTrue(ok, error)
            current = runtime.current(owner, bpy.context.scene, item)[1]
            self.assertLess(max((p - q - Vector((0, 0, height))).length for p, q in zip(current, points)), 1e-5)

    def test_commit_failure_restores_state_and_curve(self):
        owner, _surface, item, points = fixture(); service.configure_mode(owner, bpy.context.scene, item, 'FREE')
        payload, current = runtime.current(owner, bpy.context.scene, item); before = item.free_path_json
        changed = list(current); changed[1] = changed[1] + Vector((0, 0, .1))
        with patch.object(service, 'rebuild', side_effect=ValueError('Injected downstream failure')):
            with self.assertRaises(ValueError): service.commit(owner, bpy.context.scene, item, payload, changed)
        self.assertEqual(item.free_path_json, before)
        self.assertEqual(points, persisted_fiber_points(bpy.context.scene, owner.name, item.id))

    def test_free_recompute_has_no_preflight_or_planner(self):
        from anthroforge.core.visualization import fiber_refinement as refinement
        owner, _surface, item, _points = fixture(); service.configure_mode(owner, bpy.context.scene, item, 'FREE')
        with patch.object(refinement, '_hard_anchor_preflight', side_effect=AssertionError('preflight')):
            token = refinement.request_fiber_refinement_group(owner, bpy.context.scene, [item.id])
        state = refinement.fiber_refinement_group_state(token)
        self.assertTrue(state['done']); self.assertEqual(state['failures'], {})
        self.assertEqual(state['committed'], (item.id,))
