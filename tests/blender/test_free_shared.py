from unittest.mock import patch
import bpy
import numpy as np
from mathutils import Vector
from _helpers import BlenderTestCase, fiber, capture_world_attachment
from test_free_fibers import fixture
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.core.vcp import free_path, shared_point_storage as storage
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization import free_fiber_runtime as runtime
from anthroforge.core.visualization.fiber_sync import register_fiber_sync


def shared_fixture():
    owner, surface, first, points = fixture()
    with suppress_vcp_prop_updates():
        second = fiber(owner, first.a_parent_id, first.b_parent_id); second.a_point_id = first.a_point_id
        second.b_point_id = first.b_point_id
        controlled = fiber(owner, first.a_parent_id, first.b_parent_id); controlled.a_point_id = first.a_point_id
    register_fiber_sync().apply_points(owner, bpy.context.scene, second, points)
    service.configure_mode(owner, bpy.context.scene, first, 'FREE')
    service.configure_mode(owner, bpy.context.scene, second, 'FREE')
    return owner, first, second, controlled, points


class FreeSharedTests(BlenderTestCase):
    def test_rna_edit_adjusts_all_incident_free_and_schedules_only_controlled(self):
        owner, first, second, controlled, points = shared_fixture()
        raw = capture_world_attachment(owner, first.a_parent_id, Vector((.15, .2, 0)))
        with patch('anthroforge.app.runtime_api.schedule_context') as schedule:
            first.a_attach_param = raw
        expected = free_path.adjust_anchors(points, [0, 3], [(.15, .2, 0), points[-1]])
        for item in (first, second): np.testing.assert_allclose(runtime.current(owner, bpy.context.scene, item)[1], expected, atol=1e-6)
        self.assertEqual(schedule.call_count, 1)
        self.assertEqual(schedule.call_args.kwargs['dirty_hints']['FIBER'], {controlled.id})

    def test_failed_incident_update_restores_point_and_both_curves(self):
        owner, first, second, _controlled, points = shared_fixture()
        previous = [f.free_path_json for f in (first, second)]; old_raw = first.a_attach_param
        point = storage.point_record(first, 'a_point_id')
        with suppress_vcp_prop_updates(): point.attach_param = capture_world_attachment(owner, first.a_parent_id, Vector((.2, .2, 0)))
        with patch.object(service, 'rebuild', side_effect=ValueError('downstream')):
            with self.assertRaises(ValueError): storage.point_updated(point, bpy.context)
        self.assertEqual(first.a_attach_param, old_raw); self.assertEqual(second.a_attach_param, old_raw)
        self.assertEqual([f.free_path_json for f in (first, second)], previous)
        for item in (first, second): np.testing.assert_allclose(runtime.current(owner, bpy.context.scene, item)[1], points, atol=1e-6)
