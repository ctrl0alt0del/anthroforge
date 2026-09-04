from pathlib import Path
import sys
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, empty_object, mesh_object, root, scp_with_object
from anthroforge.core.visualization import sync_runner
from core.scp_runtime.attachment_runtime import apply_scp_attachments, capture_attachment_from_link
from core.scp_runtime.attachment_wave_capture import plan_attachment_waves
from core.scp_runtime.attachment_wave_runtime import last_attachment_wave_report
from core.scp_runtime import surface as surface_runtime
from core.scp_runtime.common import scp_prop_map
from core.scp_runtime.lookup import set_parent_relation
from core.scp_runtime.object_roles import set_scp_geometry_object
from core.scp_runtime.prop_update_guard import set_parent_id_raw
from core.scp_runtime.runtime_state import attach_child_origin_local, set_attach_initialized
from core.vcp.attachment_backend import capture_attachment_from_mesh_vertex, resolve_attachment_world


def _world_verts(obj):
    return [tuple(round(float(v), 4) for v in (obj.matrix_world @ vert.co)) for vert in obj.data.vertices]


def _reset_sync_runner():
    sync_runner._RUNNING = False
    sync_runner._TIMER_ARMED = False
    sync_runner._TIMER_DUE_AT = 0.0
    sync_runner._PENDING.clear()


def _force_pending_due():
    for item in sync_runner._PENDING:
        item.due_at = sync_runner._now()


def _flush_attachment_runtime():
    for _ in range(5):
        _force_pending_due()
        state = sync_runner._flush_pending()
        bpy.context.view_layer.update()
        if state is None:
            return


def _capture_object_origin_link(parent, child):
    child.attach_parent_anchor_mode = child.attach_child_anchor_mode = "OBJECT_ORIGIN"
    set_parent_relation(child.transform_object_ref, child, parent.transform_object_ref)
    return capture_attachment_from_link(child, child.transform_object_ref, None, parent.transform_object_ref, None)


def _object_origin_chain():
    root_obj = root()
    top = scp_with_object(root_obj, "Top", empty_object("Top"), with_geometry=False)
    mid = scp_with_object(root_obj, "Mid", empty_object("Mid", (1.0, 0.0, 0.0)), with_geometry=False)
    child = scp_with_object(root_obj, "Child", empty_object("Child", (2.0, 0.0, 0.0)), with_geometry=False)
    _capture_object_origin_link(top, mid)
    _capture_object_origin_link(mid, child)
    return root_obj, top, mid, child


def _surface_child_chain():
    root_obj = root()
    top = scp_with_object(root_obj, "Top", empty_object("Top"), with_geometry=False)
    mid = scp_with_object(root_obj, "Mid", mesh_object("Mid"), with_geometry=True)
    child = scp_with_object(root_obj, "Child", empty_object("Child", (0.3333, 0.3333, 0.0)), with_geometry=False)
    mid.attach_parent_anchor_mode = mid.attach_child_anchor_mode = "OBJECT_ORIGIN"
    child.attach_parent_anchor_mode, child.attach_child_anchor_mode = "SURFACE_NEAREST", "OBJECT_ORIGIN"
    set_parent_relation(mid.transform_object_ref, mid, top.transform_object_ref)
    set_parent_relation(child.transform_object_ref, child, mid.transform_object_ref)
    capture_attachment_from_link(mid, mid.transform_object_ref, mid.geometry_object_ref, top.transform_object_ref, None)
    capture_attachment_from_link(child, child.transform_object_ref, None, mid.transform_object_ref, mid.geometry_object_ref)
    return root_obj, top, mid, child


def _offset_mesh_z(obj, distance):
    for vert in obj.data.vertices:
        vert.co.z += distance
    obj.data.update()


def _move_surface_binding(root_obj, parent):
    scene, mesh = bpy.context.scene, parent.geometry_object_ref.data
    raw = capture_attachment_from_mesh_vertex(root_obj, scene, parent.id, 1)
    before = resolve_attachment_world(root_obj, scene, parent.id, raw)
    mesh.vertices[1].co.z = 1.25
    mesh.update()
    after = resolve_attachment_world(root_obj, scene, parent.id, raw)
    return before, after


def _large_surface_binding(root_obj, count=300):
    mesh = bpy.data.meshes.new("LargeParent")
    vertices = [(float(i), float(i % 2), 0.0) for i in range(count)]
    mesh.from_pydata(vertices, (), [(0, index, index + 1) for index in range(1, count - 1, 2)])
    obj = bpy.data.objects.new("LargeParent", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return scp_with_object(root_obj, "LargeParent", obj)


class AttachmentPipelineTests(BlenderTestCase):
    def test_attachment_capture_uses_vertex_only_payload(self):
        obj = mesh_object("AttachmentVertices")
        depsgraph = bpy.context.evaluated_depsgraph_get()
        payload = surface_runtime.build_mesh_attachment_vertices(obj, depsgraph)
        self.assertEqual((payload["verts_local"].shape, payload["triangles"]), ((3, 3), ()))

    def test_sibling_attachments_share_one_wave(self):
        root_obj = root(); parent = scp_with_object(root_obj, "Parent", empty_object("Parent"), with_geometry=False)
        left = scp_with_object(root_obj, "Left", empty_object("Left"), with_geometry=False)
        right = scp_with_object(root_obj, "Right", empty_object("Right"), with_geometry=False)
        _capture_object_origin_link(parent, left); _capture_object_origin_link(parent, right)
        waves, issues = plan_attachment_waves(scp_prop_map(root_obj), (), {parent.id})
        self.assertEqual((waves, issues), ((tuple(sorted((left.id, right.id))),), ()))

    def test_attachment_cycle_blocks_only_its_component(self):
        root_obj = root(); left = scp_with_object(root_obj, "Left", empty_object("Left"), with_geometry=False)
        right = scp_with_object(root_obj, "Right", empty_object("Right"), with_geometry=False)
        set_parent_id_raw(left, right.id); set_parent_id_raw(right, left.id)
        set_attach_initialized(left, True); set_attach_initialized(right, True)
        waves, issues = plan_attachment_waves(scp_prop_map(root_obj), {left.id, right.id}, ())
        self.assertEqual(waves, ()); self.assertEqual({row[0] for row in issues}, {left.id, right.id})

    def test_missing_native_capability_uses_recorded_serial_fallback(self):
        root_obj, parent, mid, _child = _object_origin_chain()
        parent.transform_object_ref.location.z = 2.0
        target = "core.scp_runtime.attachment_wave_runtime.attachment_wave_status"
        with patch(target, return_value=False):
            changed = apply_scp_attachments(None, root_obj, bpy.context.scene,
                scp_prop_map(root_obj), parent_ids={parent.id})
        report = last_attachment_wave_report(root_obj)
        self.assertIn(mid.id, changed); self.assertEqual(report.fallback_reason, "NATIVE_ATTACHMENT_UNAVAILABLE")

    def test_surface_binding_refreshes_after_direct_mesh_update(self):
        root_obj = root()
        parent = scp_with_object(root_obj, "Parent", mesh_object("Parent"))
        with patch.object(surface_runtime, "geometry_generation", return_value=0):
            before, after = _move_surface_binding(root_obj, parent)
        self.assertEqual((round(before.z, 4), round(after.z, 4)), (0.0, 1.25))

    def test_pending_update_fingerprints_every_large_mesh_vertex(self):
        root_obj, index = root(), 257
        parent = _large_surface_binding(root_obj)
        raw = capture_attachment_from_mesh_vertex(root_obj, bpy.context.scene, parent.id, index)
        before = resolve_attachment_world(root_obj, bpy.context.scene, parent.id, raw)
        parent.geometry_object_ref.data.vertices[index].co.z = 1.25
        parent.geometry_object_ref.data.update()
        after = resolve_attachment_world(root_obj, bpy.context.scene, parent.id, raw)
        self.assertEqual((round(before.z, 4), round(after.z, 4)), (0.0, 1.25))

    def test_object_origin_attachment_tracks_parent_move(self):
        root_obj = root()
        parent_obj = empty_object("Parent", (0.0, 0.0, 0.0))
        child_obj = empty_object("Child", (2.0, 0.0, 0.0))
        parent = scp_with_object(root_obj, "Parent", parent_obj, with_geometry=False)
        child = scp_with_object(root_obj, "Child", child_obj, with_geometry=False)
        child.attach_parent_anchor_mode = "OBJECT_ORIGIN"
        child.attach_child_anchor_mode = "OBJECT_ORIGIN"
        set_parent_relation(child_obj, child, parent_obj)
        self.assertTrue(capture_attachment_from_link(child, child_obj, None, parent_obj, None))
        parent_obj.location.z = 3.0
        changed = apply_scp_attachments(None, root_obj, bpy.context.scene, scp_prop_map(root_obj), parent_ids={parent.id})
        self.assertIn(child.id, changed)
        self.assertEqual(tuple(round(v, 4) for v in child_obj.location), (2.0, 0.0, 3.0))

    def test_apply_keeps_stored_child_anchor_when_child_mesh_deforms(self):
        root_obj = root()
        parent = scp_with_object(root_obj, "Parent", empty_object("Parent"), with_geometry=False)
        child = scp_with_object(root_obj, "Child", mesh_object("Child", (1.0, 0.0, 0.0)))
        child.attach_parent_anchor_mode = "OBJECT_ORIGIN"
        set_parent_relation(child.transform_object_ref, child, parent.transform_object_ref)
        self.assertTrue(capture_attachment_from_link(child, child.transform_object_ref, child.geometry_object_ref, parent.transform_object_ref, None))
        start = tuple(round(v, 4) for v in child.transform_object_ref.location)
        child.geometry_object_ref.data.vertices[0].co.x += 5.0
        child.geometry_object_ref.data.update()
        changed = apply_scp_attachments(None, root_obj, bpy.context.scene, scp_prop_map(root_obj), parent_ids={parent.id})
        self.assertEqual((changed, tuple(round(v, 4) for v in child.transform_object_ref.location)), (set(), start))

    def test_chain_apply_ignores_live_mid_mesh_anchor(self):
        root_obj = root()
        top = scp_with_object(root_obj, "Top", empty_object("Top"), with_geometry=False)
        mid = scp_with_object(root_obj, "Mid", mesh_object("Mid", (1.0, 0.0, 0.0)))
        child = scp_with_object(root_obj, "Child", empty_object("Child", (2.0, 0.0, 0.0)), with_geometry=False)
        mid.attach_parent_anchor_mode, mid.attach_child_anchor_mode = "OBJECT_ORIGIN", "FACE_CENTER"
        child.attach_parent_anchor_mode = child.attach_child_anchor_mode = "OBJECT_ORIGIN"
        for item, geom, parent_obj in ((mid, mid.geometry_object_ref, top.transform_object_ref), (child, None, mid.transform_object_ref)):
            set_parent_relation(item.transform_object_ref, item, parent_obj); self.assertTrue(capture_attachment_from_link(item, item.transform_object_ref, geom, parent_obj, None))
        mid.geometry_object_ref.data.vertices[0].co.x += 5.0
        mid.geometry_object_ref.data.update()
        top.transform_object_ref.location.x = 3.0
        changed = apply_scp_attachments(None, root_obj, bpy.context.scene, scp_prop_map(root_obj), parent_ids={top.id})
        self.assertEqual((changed, tuple(round(v, 4) for v in mid.transform_object_ref.location), tuple(round(v, 4) for v in child.transform_object_ref.location)), ({mid.id, child.id}, (4.0, 0.0, 0.0), (5.0, 0.0, 0.0)))

    def test_depsgraph_apply_keeps_directly_moved_mid_scp(self):
        self.addCleanup(_reset_sync_runner)
        _reset_sync_runner()
        _, _, mid, child = _object_origin_chain()
        bpy.context.view_layer.update()
        _reset_sync_runner()
        mid.transform_object_ref.location.x = 3.0
        bpy.context.view_layer.update()
        _flush_attachment_runtime()
        self.assertEqual(tuple(round(v, 4) for v in mid.transform_object_ref.location), (3.0, 0.0, 0.0))
        self.assertEqual(tuple(round(v, 4) for v in child.transform_object_ref.location), (4.0, 0.0, 0.0))

    def test_targeted_mid_geometry_update_propagates_to_child(self):
        root_obj, top, mid, child = _surface_child_chain()
        _offset_mesh_z(mid.geometry_object_ref, 1.0)
        changed = apply_scp_attachments(None, root_obj, bpy.context.scene, scp_prop_map(root_obj), {mid.id, child.id}, {top.id})
        self.assertEqual(changed, {child.id})
        self.assertEqual(tuple(round(v, 4) for v in child.transform_object_ref.location), (0.3333, 0.3333, 1.0))

    def test_global_attachment_toggle_freezes_and_rebinds_current_pose(self):
        root_obj = root()
        parent_obj = empty_object("Parent", (0.0, 0.0, 0.0))
        child_obj = empty_object("Child", (2.0, 0.0, 0.0))
        parent = scp_with_object(root_obj, "Parent", parent_obj, with_geometry=False)
        child = scp_with_object(root_obj, "Child", child_obj, with_geometry=False)
        child.attach_parent_anchor_mode = child.attach_child_anchor_mode = "OBJECT_ORIGIN"
        set_parent_relation(child_obj, child, parent_obj)
        self.assertTrue(capture_attachment_from_link(child, child_obj, None, parent_obj, None))
        bpy.context.scene.af_attachments_enabled = False
        parent_obj.location.x = 3.0
        changed = apply_scp_attachments(None, root_obj, bpy.context.scene, scp_prop_map(root_obj), parent_ids={parent.id})
        self.assertEqual((changed, tuple(round(v, 4) for v in child_obj.location)), (set(), (2.0, 0.0, 0.0)))
        bpy.context.scene.af_attachments_enabled = True
        self.assertEqual(tuple(round(v, 4) for v in child_obj.location), (2.0, 0.0, 0.0))
        parent_obj.location.x = 4.0
        changed = apply_scp_attachments(None, root_obj, bpy.context.scene, scp_prop_map(root_obj), parent_ids={parent.id})
        self.assertEqual((changed, tuple(round(v, 4) for v in child_obj.location)), ({child.id}, (3.0, 0.0, 0.0)))

    def test_move_origin_to_attachment_preserves_pose_and_recaptures(self):
        root_obj = root()
        parent = scp_with_object(root_obj, "Parent", empty_object("Parent"), with_geometry=False)
        child = scp_with_object(root_obj, "Child", mesh_object("Child", (2.0, 0.0, 0.0)))
        child.attach_parent_anchor_mode, child.attach_child_anchor_mode = "OBJECT_ORIGIN", "FACE_CENTER"
        set_parent_relation(child.transform_object_ref, child, parent.transform_object_ref)
        self.assertTrue(capture_attachment_from_link(child, child.transform_object_ref, child.geometry_object_ref, parent.transform_object_ref, None))
        before = _world_verts(child.transform_object_ref)
        child.transform_object_ref.select_set(True)
        bpy.context.view_layer.objects.active = child.transform_object_ref
        self.assertEqual(bpy.ops.af.move_scp_origin_to_attachment(), {"FINISHED"})
        after = _world_verts(child.transform_object_ref)
        anchor = tuple(round(float(v), 4) for v in attach_child_origin_local(child))
        self.assertEqual(before, after)
        self.assertEqual(anchor, (0.0, 0.0, 0.0))
        parent.transform_object_ref.location.z = 3.0
        changed = apply_scp_attachments(None, root_obj, bpy.context.scene, scp_prop_map(root_obj), parent_ids={parent.id})
        self.assertEqual((changed, round(float(child.transform_object_ref.location.z), 4)), ({child.id}, 3.0))

    def test_move_origin_to_attachment_keeps_separate_geometry_pose(self):
        root_obj = root()
        parent = scp_with_object(root_obj, "Parent", empty_object("Parent"), with_geometry=False)
        child = scp_with_object(root_obj, "Child", empty_object("Child"), with_geometry=False)
        geo = mesh_object("ChildGeo", (2.0, 0.0, 0.0))
        set_scp_geometry_object(root_obj, child, geo)
        child.attach_parent_anchor_mode, child.attach_child_anchor_mode = "OBJECT_ORIGIN", "FACE_CENTER"
        set_parent_relation(child.transform_object_ref, child, parent.transform_object_ref)
        self.assertTrue(capture_attachment_from_link(child, child.transform_object_ref, child.geometry_object_ref, parent.transform_object_ref, None))
        before = _world_verts(child.geometry_object_ref)
        child.transform_object_ref.select_set(True)
        bpy.context.view_layer.objects.active = child.transform_object_ref
        self.assertEqual(bpy.ops.af.move_scp_origin_to_attachment(), {"FINISHED"})
        after = _world_verts(child.geometry_object_ref)
        anchor = tuple(round(float(v), 4) for v in attach_child_origin_local(child))
        self.assertEqual(before, after)
        self.assertEqual(anchor, (0.0, 0.0, 0.0))
