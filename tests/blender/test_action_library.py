from pathlib import Path
import sys
from math import pi

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, add_shortcut, empty_object, root, scp_with_object, select_only
from core.local_transform_props import local_transform_keys


def _round_xyz(obj):
    return tuple(round(float(value), 4) for value in obj.location)


class ActionLibraryTests(BlenderTestCase):
    def test_create_local_transform_props_drives_location_in_local_space(self):
        obj = empty_object("Guide")
        obj.rotation_euler.z = pi / 2.0
        select_only(obj)
        self.assertEqual(bpy.ops.af.create_local_transform_props(), {"FINISHED"})
        obj[local_transform_keys()[0]] = 2.0
        obj.update_tag()
        bpy.context.view_layer.update()
        self.assertEqual(_round_xyz(obj), (0.0, 2.0, 0.0))

    def test_shortcut_can_drive_local_transform_property(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Guide", empty_object("Guide"), with_geometry=False)
        scp.transform_object_ref.rotation_euler.z = pi / 2.0
        select_only(scp.transform_object_ref)
        self.assertEqual(bpy.ops.af.create_local_transform_props(), {"FINISHED"})
        path = f'bpy.data.objects["{scp.transform_object_ref.name}"]["{local_transform_keys()[0]}"]'
        shortcut = add_shortcut(root_obj, "Local X", "SCP", scp.id, path)
        shortcut.proxy_float = 2.0
        bpy.context.view_layer.update()
        self.assertEqual(_round_xyz(scp.transform_object_ref), (0.0, 2.0, 0.0))

    def test_remove_local_transform_props_preserves_current_location(self):
        obj = empty_object("Guide")
        obj.rotation_euler.z = pi / 2.0
        select_only(obj)
        bpy.ops.af.create_local_transform_props()
        obj[local_transform_keys()[0]] = 2.0
        obj.update_tag()
        bpy.context.view_layer.update()
        self.assertEqual(_round_xyz(obj), (0.0, 2.0, 0.0))
        self.assertEqual(bpy.ops.af.remove_local_transform_props(), {"FINISHED"})
        self.assertEqual(_round_xyz(obj), (0.0, 2.0, 0.0))
        self.assertFalse(any(key in obj for key in local_transform_keys()))
        self.assertIsNone(next((fc for fc in tuple(getattr(getattr(obj, "animation_data", None), "drivers", ()) or ()) if fc.data_path == "location"), None))
