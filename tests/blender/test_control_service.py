from pathlib import Path
import sys

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, empty_object, root, scp_with_object, select_only
from anthroforge.core.visualization.control_runtime import notify_selection_changed


class ControlServiceTests(BlenderTestCase):
    def test_mark_control_and_toggle_axis_shortcut(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Arm", empty_object("Arm"), with_geometry=False)
        ctrl = empty_object("CTRL", (1.0, 2.0, 3.0))
        bpy.context.scene.af_control_scp_obj = scp.transform_object_ref
        select_only(ctrl)
        self.assertEqual(bpy.ops.af.mark_selected_scp_control_object(), {"FINISHED"})
        self.assertEqual((ctrl["af_scp_control"], len(root_obj.af_shortcut_system.shortcuts)), (True, 0))
        self.assertEqual(bpy.ops.af.toggle_control_object_shortcut_axis(axis="X"), {"FINISHED"})
        self.assertEqual(root_obj.af_shortcut_system.shortcuts[0].owner_id, scp.id)
        bpy.ops.af.toggle_control_object_shortcut_axis(axis="X")
        self.assertEqual(len(root_obj.af_shortcut_system.shortcuts), 0)

    def test_toggle_control_apply_parent_keeps_world_space(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Arm", empty_object("Arm"), with_geometry=False)
        ctrl = empty_object("CTRL", (1.0, 2.0, 3.0))
        bpy.context.scene.af_control_scp_obj = scp.transform_object_ref
        select_only(ctrl)
        bpy.ops.af.mark_selected_scp_control_object()
        world = tuple(round(v, 4) for v in ctrl.matrix_world.translation)
        bpy.ops.af.toggle_control_object_apply_parent()
        self.assertEqual((ctrl.parent, tuple(round(v, 4) for v in ctrl.matrix_world.translation)), (scp.transform_object_ref, world))
        self.assertEqual(bpy.ops.af.toggle_control_object_apply_parent(), {"FINISHED"})

    def test_notify_selection_changed_resolves_control_owner(self):
        root_obj = root()
        scp_with_object(root_obj, "Left", empty_object("Left"), with_geometry=False)
        right = scp_with_object(root_obj, "Right", empty_object("Right"), with_geometry=False)
        ctrl = empty_object("CTRL")
        ctrl["af_scp_control"], ctrl["af_root_name"], ctrl["af_scp_id"] = True, root_obj.name, right.id
        select_only(ctrl)
        notify_selection_changed(bpy.context.scene, force=True)
        self.assertEqual(root_obj.af_scp_system.scps[root_obj.af_scp_system.active_scp_index].id, right.id)
