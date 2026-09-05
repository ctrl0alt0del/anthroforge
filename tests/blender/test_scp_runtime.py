from pathlib import Path
import sys
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, mesh_object, root, scp_with_object
from core.scp_runtime.bound_objects import set_bound_native_parenting, sync_scp_roles
from core.scp_runtime.object_roles import add_bound_object_to_scp, create_scp


class ScpRuntimeTests(BlenderTestCase):
    def test_create_scp_seeds_defaults_and_active_index(self):
        root_obj = root()
        scp = create_scp(root_obj, "Arm")
        self.assertEqual((scp.id, scp.name, root_obj.af_scp_system.active_scp_index), ("SCP_1", "SCP_1", 0))
        self.assertEqual((scp.attach_parent_anchor_mode, scp.attach_child_anchor_mode, scp.attach_follow_rotation), ("SURFACE_NEAREST", "FACE_CENTER", True))

    def test_role_binding_tags_identity_and_parenting(self):
        root_obj = root()
        xform = mesh_object("XFORM")
        geom = mesh_object("GEOM")
        extra = mesh_object("EXTRA")
        item = scp_with_object(root_obj, "Arm", xform, with_geometry=False)
        self.assertTrue(add_bound_object_to_scp(root_obj, item, geom))
        self.assertTrue(add_bound_object_to_scp(root_obj, item, extra))
        self.assertTrue(set_bound_native_parenting(root_obj, item, item.bound_objects[2].id, False))
        sync_scp_roles(root_obj, item)
        self.assertEqual((xform["af_scp_transform"], geom["af_scp_geometry"]), (True, False))
        self.assertEqual((item.name, extra.parent), ("XFORM", None))

    def test_object_cannot_be_bound_to_two_scps(self):
        root_obj = root()
        obj = mesh_object("BOUND")
        first = scp_with_object(root_obj, "First", obj)
        second = scp_with_object(root_obj, "Second", mesh_object("SECOND"))
        self.assertEqual(len(first.bound_objects), 1)
        self.assertFalse(add_bound_object_to_scp(root_obj, second, obj))

    def test_sync_roles_propagates_scp_color(self):
        root_obj = root()
        item = scp_with_object(root_obj, "Arm", mesh_object("Arm"))
        item.color, item.color_initialized = (0.1, 0.2, 0.3, 1.0), True
        sync_scp_roles(root_obj, item)
        self.assertEqual(tuple(round(v, 4) for v in item.transform_object_ref.color), (0.1, 0.2, 0.3, 1.0))

    def test_role_sync_identity_does_not_emit_property_requests(self):
        from anthroforge.properties import scp_properties
        root_obj = root()
        item = scp_with_object(root_obj, "Arm", mesh_object("Identity"))
        with patch.object(scp_properties, "sync_context") as sync:
            sync_scp_roles(root_obj, item)
            item.transform_object_ref.name = "Renamed"
            sync_scp_roles(root_obj, item)
            self.assertEqual((item.name, sync.call_count), ("Renamed", 0))
            item.name = "User Authored"
        self.assertEqual(sync.call_count, 1)
