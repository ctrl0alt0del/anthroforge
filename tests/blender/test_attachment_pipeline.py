from pathlib import Path
import sys

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, empty_object, root, scp_with_object
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
