from pathlib import Path
from dataclasses import replace
import sys
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path: sys.path.insert(0, value)

import bpy
from mathutils import Vector

from _helpers import BlenderTestCase, capture_world_attachment, fiber, mesh_object, root, scp_with_object
from core.deps.builtin_drivers import FiberSyncDriver, SCPSyncDriver
from core.vcp.fiber_node_attachment import (capture_fiber_node_attachments,
                                            resolve_fiber_node_attachments)
from core.vcp.fiber_node_attachment_codec import (decode_node_attachments, encode_node_attachments,
                                                   node_attachment_target_ids)
from core.vcp.runtime_state import fiber_recompute_status
from core.vcp.prop_update_guard import suppress_vcp_prop_updates
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


def _instance_fixture():
    r, scp, surface, item, points = _fixture()
    with suppress_vcp_prop_updates():
        r['af_authoring_id'] = 'root'; surface['af_authoring_root_id'] = 'root'
        surface['af_authoring_id'] = 'instance'
        item.a_parent_id = item.b_parent_id = 'AFI_instance'
    assert capture_fiber_node_attachments(r, bpy.context.scene, item, points).ok
    return r, scp, surface, item, points


class FiberNodeAttachmentTests(BlenderTestCase):
    def test_instance_map_rejects_duplicates_and_respects_root_scope(self):
        from core.scp_runtime.common import instance_geometry_objects
        r, _scp, surface, _item, _points = _instance_fixture()
        duplicate = surface.copy(); bpy.context.scene.collection.objects.link(duplicate)
        self.assertNotIn('AFI_instance',instance_geometry_objects(bpy.context.scene,r.name))
        duplicate['af_authoring_root_id']='other-root'
        self.assertEqual(instance_geometry_objects(bpy.context.scene,r.name)['AFI_instance'],surface)
        bpy.data.objects.remove(duplicate,do_unlink=True)
        self.assertEqual(instance_geometry_objects(bpy.context.scene,r.name)['AFI_instance'],surface)

    def test_load_resolves_saved_instance_nodes_without_solving(self):
        root_obj, _scp, surface, item, _points = _instance_fixture()
        surface.location.z = .4; bpy.context.view_layer.update()
        with patch("core.visualization.fiber_refinement.request_fiber_refinement") as request:
            FiberSyncDriver().sync(root_obj, bpy.context.scene, True, {"FIBER": set()}, False, {"event_type": "LOAD"})
        moved = persisted_fiber_points(bpy.context.scene, root_obj.name, item.id)
        self.assertEqual(request.call_count, 0)
        self.assertTrue(all(abs(p.z-.45) < 1e-6 for p in moved))

    def test_instance_nodes_survive_cleanup_and_native_wave(self):
        from core.visualization.delete_reconcile import cleanup_scp_dependents
        from core.scp_runtime.attachment_wave_runtime import last_attachment_wave_report
        from core.deps.adapters import _fiber_attachment_ids
        r, scp, surface, item, _points = _instance_fixture()
        self.assertEqual(_fiber_attachment_ids(r, item), (scp.id,))
        self.assertFalse(cleanup_scp_dependents(r)); self.assertTrue(item.node_attachments_json)
        surface.location.z = .4; bpy.context.view_layer.update()
        impacted = {'SCP': {scp.id}, 'FIBER': {item.id}}
        SCPSyncDriver().sync(r, bpy.context.scene, False, impacted, False, {'event_type': 'UPDATE'})
        report = last_attachment_wave_report(r)
        self.assertEqual(report.failed_fibers, ()); self.assertIn(item.id, report.handled_fibers)
        self.assertTrue(all(abs(p.z-.45) < 1e-6 for p in persisted_fiber_points(bpy.context.scene, r.name, item.id)))

    def test_deleted_instance_still_removes_dependent_fiber(self):
        from core.visualization.delete_reconcile import cleanup_scp_dependents
        r, _scp, surface, _item, _points = _instance_fixture()
        bpy.data.objects.remove(surface, do_unlink=True)
        self.assertTrue(cleanup_scp_dependents(r))
        self.assertEqual(len(r.af_vcp_system.fibers), 0)

    def test_instance_nodes_follow_a_reflected_surface(self):
        root_obj, _scp, surface, item, points = _fixture()
        with suppress_vcp_prop_updates():
            root_obj['af_authoring_id'] = 'root'; surface['af_authoring_root_id'] = 'root'
            surface['af_authoring_id'] = 'mirror'
            item.a_parent_id = item.b_parent_id = 'AFI_mirror'
        surface.scale.x = -1; points = tuple(Vector((-p.x,p.y,p.z)) for p in points)
        result = capture_fiber_node_attachments(root_obj, bpy.context.scene, item, points)
        self.assertTrue(result.ok, result.error)
        self.assertIn('AFI_mirror', node_attachment_target_ids(item))
        surface.location.z = .4; bpy.context.view_layer.update()
        moved = resolve_fiber_node_attachments(root_obj, bpy.context.scene, item)
        self.assertTrue(moved.ok, moved.error)
        self.assertTrue(all(abs(p.z-.45) < 1e-6 for p in moved.points))

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

    def test_scp_driver_resolves_nodes_and_skips_later_serial_pass(self):
        root_obj, scp, surface, item, points = _fixture()
        self.assertTrue(capture_fiber_node_attachments(root_obj, bpy.context.scene, item, points).ok)
        surface.location.z = 0.4; bpy.context.view_layer.update()
        impacted = {"SCP": {scp.id}, "FIBER": {item.id}}
        meta = {"runtime_dirty_ids_by_type": {"SCP": [scp.id]}, "event_type": "UPDATE"}
        target = "core.visualization.fiber_node_attachment_runtime._apply_fiber_node_attachments_serial"
        with patch(target) as serial, patch("core.visualization.fiber_refinement.request_fiber_refinement") as request:
            SCPSyncDriver().sync(root_obj, bpy.context.scene, False, impacted, False, meta)
            FiberSyncDriver().sync(root_obj, bpy.context.scene, False, impacted, False, meta)
        moved = persisted_fiber_points(bpy.context.scene, root_obj.name, item.id)
        self.assertEqual((serial.call_count, request.call_count), (0, 0))
        self.assertTrue(all(abs(point.z - 0.45) < 1.0e-6 for point in moved))

    def test_load_hydrates_missing_node_attachments_without_solving(self):
        root_obj, scp, _surface, item, _points = _fixture()
        item.node_attachments_json = ""
        captured = capture_missing_fiber_node_attachments(root_obj, bpy.context.scene, {item.id})
        self.assertEqual(captured, {item.id})
        self.assertEqual(node_attachment_target_ids(item), (scp.id,))

    def test_invalid_node_causes_atomic_fiber_rollback(self):
        root_obj, scp, surface, item, points = _fixture()
        self.assertTrue(capture_fiber_node_attachments(root_obj, bpy.context.scene, item, points).ok)
        payload = decode_node_attachments(item.node_attachments_json)
        nodes = (replace(payload.nodes[0], attach_raw="{}"),) + payload.nodes[1:]
        item.node_attachments_json = encode_node_attachments(replace(payload, nodes=nodes))
        before = persisted_fiber_points(bpy.context.scene, root_obj.name, item.id)
        impacted = {"SCP": {scp.id}, "FIBER": {item.id}}
        SCPSyncDriver().sync(root_obj, bpy.context.scene, False, impacted, False, {"event_type": "UPDATE"})
        after = persisted_fiber_points(bpy.context.scene, root_obj.name, item.id)
        self.assertEqual(tuple(before), tuple(after)); self.assertEqual(fiber_recompute_status(item), "INVALID_ATTACHMENT")
