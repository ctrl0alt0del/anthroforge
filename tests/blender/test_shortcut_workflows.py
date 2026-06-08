from pathlib import Path
import sys

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, mesh_object, root, scp_with_object, select_only


class ShortcutWorkflowTests(BlenderTestCase):
    def test_add_and_delete_data_shortcut_operator(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Arm", mesh_object("Arm"))
        select_only(scp.transform_object_ref)
        bpy.context.scene.af_new_shortcut_name = "Arm X"
        bpy.context.scene.af_new_shortcut_path = f'bpy.data.objects["{scp.transform_object_ref.name}"].location[0]'
        self.assertEqual(bpy.ops.af.add_data_shortcut(), {"FINISHED"})
        shortcut_id = root_obj.af_shortcut_system.shortcuts[0].id
        self.assertEqual(bpy.ops.af.delete_data_shortcut(shortcut_id=shortcut_id), {"FINISHED"})
        self.assertEqual(len(root_obj.af_shortcut_system.shortcuts), 0)
