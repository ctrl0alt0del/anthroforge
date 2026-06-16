from pathlib import Path
import sys

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, empty_object, mesh_object, root, scp_with_object
from core.scp_runtime.attachment_runtime import apply_scp_attachments, capture_attachment_from_link
from core.scp_runtime.common import scp_prop_map
from core.scp_runtime.lookup import set_parent_relation


class AttachmentPipelineTests(BlenderTestCase):
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
