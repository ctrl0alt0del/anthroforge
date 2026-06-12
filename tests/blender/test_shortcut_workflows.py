from pathlib import Path
import sys

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, add_shortcut, mesh_object, root, scp_with_object, select_only
from app.use_cases.shortcut_edit import apply_shortcut_proxy, prime_shortcut_proxy
from core.scp_runtime.lookup import set_parent_relation
from core.scp_runtime.runtime_state import attach_parent_param
from core.shortcuts import resolve_shortcut, upsert_override
from core.shortcuts.proxy_props import proxy_prop_name


def _apply_float_shortcut(root_obj, shortcut, value):
    target = resolve_shortcut(root_obj, bpy.context, shortcut.data_path)
    prime_shortcut_proxy(shortcut, target)
    shortcut.proxy_sync_lock = True
    shortcut.proxy_float = value
    shortcut.proxy_sync_lock = False
    return apply_shortcut_proxy(bpy.context, shortcut)


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

    def test_indexed_transform_shortcut_writes_through_scalar_proxy(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Arm", mesh_object("Arm"))
        select_only(scp.transform_object_ref)
        shortcut = add_shortcut(root_obj, "Arm X", "SCP", scp.id, f'bpy.data.objects["{scp.transform_object_ref.name}"].location[0]')
        target = resolve_shortcut(root_obj, bpy.context, shortcut.data_path)
        self.assertEqual(proxy_prop_name(target), "proxy_float")
        setattr(shortcut, proxy_prop_name(target), 2.5)
        bpy.context.view_layer.update()
        self.assertAlmostEqual(float(scp.transform_object_ref.location[0]), 2.5, places=4)
        self.assertAlmostEqual(float(getattr(shortcut, "proxy_float")), 2.5, places=4)

    def test_shortcut_session_uses_temporary_override_only_during_apply(self):
        root_obj = root()
        parent = scp_with_object(root_obj, "Parent", mesh_object("Parent"))
        child = scp_with_object(root_obj, "Child", mesh_object("Child", (1.0, 0.0, 0.0)))
        set_parent_relation(child.transform_object_ref, child, parent.transform_object_ref)
        child.attach_parent_anchor_mode = "OBJECT_ORIGIN"
        shortcut = add_shortcut(root_obj, "Parent X", "SCP", parent.id, f'bpy.data.objects["{parent.transform_object_ref.name}"].location[0]')
        upsert_override(shortcut, child.id, "SURFACE_NEAREST", "KEEP")
        select_only(child.transform_object_ref)
        self.assertTrue(_apply_float_shortcut(root_obj, shortcut, 2.0))
        session_loc = tuple(round(float(v), 4) for v in child.transform_object_ref.location)
        bpy.context.view_layer.update()
        self.assertNotEqual(tuple(attach_parent_param(child)["tri_vidx"]), (-1, -1, -1))
        self.assertEqual(tuple(round(float(v), 4) for v in child.transform_object_ref.location), session_loc)
