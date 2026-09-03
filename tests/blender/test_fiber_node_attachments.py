from pathlib import Path
import sys
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path: sys.path.insert(0, value)

import bpy
from mathutils import Vector

from _helpers import BlenderTestCase, capture_world_attachment, fiber, mesh_object, root, scp_with_object
from core.deps.builtin_drivers import FiberSyncDriver
from core.vcp.fiber_node_attachment import (capture_fiber_node_attachments,
                                            resolve_fiber_node_attachments)
from core.vcp.fiber_node_attachment_codec import node_attachment_target_ids
from core.visualization.fiber_node_attachment_runtime import capture_missing_fiber_node_attachments
from core.visualization.fiber_sync import register_fiber_sync
from core.visualization.fiber_sync_helpers import persisted_fiber_points


def _fixture():
    root_obj = root(); surface = mesh_object("Surface")
    scp = scp_with_object(root_obj, "Surface", surface)
    item = fiber(root_obj, scp.id, scp.id); item.node_count = 8
    item.a_attach_param = capture_world_attachment(root_obj, scp.id, Vector((0.1, 0.1, 0.0)))
    item.b_attach_param = capture_world_attachment(root_obj, scp.id, Vector((0.7, 0.1, 0.0)))
    points = tuple(Vector((0.1 + 0.6 * index / 7.0, 0.1, 0.05)) for index in range(8))
    register_fiber_sync().apply_points(root_obj, bpy.context.scene, item, points)
    return root_obj, scp, surface, item, points


class FiberNodeAttachmentTests(BlenderTestCase):
    def test_nodes_follow_existing_scp_attachment(self):
        root_obj, scp, surface, item, points = _fixture()
        result = capture_fiber_node_attachments(root_obj, bpy.context.scene, item, points)
        self.assertTrue(result.ok); self.assertEqual(node_attachment_target_ids(item), (scp.id,))
        surface.location.z = 1.0; bpy.context.view_layer.update()
        moved = resolve_fiber_node_attachments(root_obj, bpy.context.scene, item)
        self.assertTrue(moved.ok, moved.error)
        self.assertTrue(all(abs(point.z - 1.05) < 1.0e-6 for point in moved.points))

    def test_propagated_scp_update_never_requests_solver(self):
        root_obj, _scp, surface, item, points = _fixture()
        self.assertTrue(capture_fiber_node_attachments(root_obj, bpy.context.scene, item, points).ok)
        surface.location.z = 0.4; bpy.context.view_layer.update()
        meta = {"runtime_dirty_ids_by_type": {"SCP": [_scp.id]}, "event_type": "UPDATE"}
        with patch("core.visualization.fiber_refinement.request_fiber_refinement") as request:
            FiberSyncDriver().sync(root_obj, bpy.context.scene, False, {"FIBER": {item.id}}, False, meta)
        moved = persisted_fiber_points(bpy.context.scene, root_obj.name, item.id)
        self.assertEqual(request.call_count, 0)
        self.assertTrue(all(abs(point.z - 0.45) < 1.0e-6 for point in moved))

    def test_load_hydrates_missing_node_attachments_without_solving(self):
        root_obj, scp, _surface, item, _points = _fixture()
        item.node_attachments_json = ""
        captured = capture_missing_fiber_node_attachments(root_obj, bpy.context.scene, {item.id})
        self.assertEqual(captured, {item.id})
        self.assertEqual(node_attachment_target_ids(item), (scp.id,))
