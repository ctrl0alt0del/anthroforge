from pathlib import Path
import sys

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, add_shortcut, empty_object, fiber, mesh_object, root, scp_with_object, select_only
from core.id_utils import next_prefixed_id
from core.scp_runtime.copy import copy_scp_subtree
from core.scp_runtime.lookup import set_parent_relation
from core.scp_runtime.object_roles import add_bound_object_to_scp
from core.scp_runtime.tree import sanitize_parent_links
from core.scp_runtime.actions import execute_reparent_scp
from core.scp_runtime.common import find_scp_by_id
from core.scp_runtime.bound_objects import set_bound_native_parenting
from core.shortcuts.path_codec import make_bound_entity_id, make_shortcut_path


class DummyOperator:
    def report(self, _level, _message):
        return None


def _new_muscle(root_obj, fiber_id):
    item = root_obj.af_vcp_system.muscles.add()
    item.id = next_prefixed_id(root_obj.af_vcp_system.muscles, "MUSCLE")
    item.name = item.id
    item.fiber_refs.add().fiber_id = fiber_id
    return item


def _new_blob(root_obj, muscle_id):
    item = root_obj.af_vcp_system.blobs.add()
    item.id = next_prefixed_id(root_obj.af_vcp_system.blobs, "BLOB")
    item.name = item.id
    item.attach_target_type, item.attach_target_id = "MUSCLE", muscle_id
    return item


def _copy_fixture(root_obj):
    parent = scp_with_object(root_obj, "Parent", mesh_object("Parent"))
    child = scp_with_object(root_obj, "Child", mesh_object("Child", (1.0, 0.0, 0.0)))
    set_parent_relation(child.transform_object_ref, child, parent.transform_object_ref)
    fib = fiber(root_obj, parent.id, child.id)
    fib.a_attach_param, fib.b_attach_param = "A", "B"
    muscle = _new_muscle(root_obj, fib.id)
    fib.muscle_id = muscle.id
    return parent, child, fib, muscle, _new_blob(root_obj, muscle.id)


class ScpTreeWorkflowTests(BlenderTestCase):
    def test_create_root_and_empty_scp_operators_seed_active_state(self):
        bpy.ops.af.create_root()
        bpy.ops.af.create_empty_scp()
        root_obj = bpy.data.objects["AF_ROOT"]
        scp = root_obj.af_scp_system.scps[0]
        self.assertEqual((len(root_obj.af_scp_system.scps), root_obj.af_scp_system.active_scp_index), (1, 0))
        self.assertEqual((scp.transform_object_ref.type, scp.transform_object_ref["af_scp_transform"]), ("EMPTY", True))

    def test_native_parenting_toggle_moves_object_without_world_shift(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Arm", empty_object("XFORM"), with_geometry=False)
        extra = mesh_object("EXTRA", (2.0, 0.0, 0.0))
        add_bound_object_to_scp(root_obj, scp, extra)
        world = tuple(round(v, 4) for v in extra.matrix_world.translation)
        set_bound_native_parenting(root_obj, scp, scp.bound_objects[1].id, False)
        self.assertEqual((tuple(round(v, 4) for v in extra.matrix_world.translation), extra.users_collection[0].name.endswith("_UNLINKED")), (world, True))
        self.assertTrue(set_bound_native_parenting(root_obj, scp, scp.bound_objects[1].id, True))

    def test_mark_scp_operator_creates_parented_binding(self):
        root_obj = root()
        parent = scp_with_object(root_obj, "Parent", mesh_object("Parent"))
        loose = mesh_object("Loose", (1.0, 0.0, 0.0))
        bpy.context.scene.af_scp_parent_obj = parent.transform_object_ref
        select_only(loose)
        self.assertEqual(bpy.ops.af.add_scp(), {"FINISHED"})
        child = next(item for item in root_obj.af_scp_system.scps if item.id != parent.id)
        self.assertEqual((child.parent_id, child.transform_object_ref, child.geometry_object_ref), (parent.id, loose, loose))
        self.assertTrue(child.attach_initialized)

    def test_reparent_cycle_is_rejected_and_invalid_parent_is_sanitized(self):
        root_obj = root()
        a = scp_with_object(root_obj, "A", empty_object("A"), with_geometry=False)
        b = scp_with_object(root_obj, "B", empty_object("B"), with_geometry=False)
        c = scp_with_object(root_obj, "C", empty_object("C"), with_geometry=False)
        set_parent_relation(b.transform_object_ref, b, a.transform_object_ref)
        set_parent_relation(c.transform_object_ref, c, b.transform_object_ref)
        self.assertEqual(execute_reparent_scp(DummyOperator(), bpy.context, a.id, c.id), {"CANCELLED"})
        c.parent_id, c.attach_initialized = "MISSING", True
        sanitize_parent_links(root_obj, {item.id: item for item in root_obj.af_scp_system.scps})
        self.assertEqual((a.parent_id, c.parent_id), ("", ""))

    def test_promote_operator_reparents_to_grandparent(self):
        root_obj = root()
        top = scp_with_object(root_obj, "Top", mesh_object("Top"))
        mid = scp_with_object(root_obj, "Mid", mesh_object("Mid", (1.0, 0.0, 0.0)))
        child = scp_with_object(root_obj, "Child", mesh_object("Child", (2.0, 0.0, 0.0)))
        set_parent_relation(mid.transform_object_ref, mid, top.transform_object_ref)
        set_parent_relation(child.transform_object_ref, child, mid.transform_object_ref)
        self.assertEqual(bpy.ops.af.promote_scp_in_tree(scp_id=child.id), {"FINISHED"})
        self.assertEqual(child.parent_id, top.id)

    def test_copy_subtree_remaps_vcps_and_shortcuts(self):
        root_obj = root()
        parent, child, fib, muscle, blob = _copy_fixture(root_obj)
        entry = child.bound_objects[0]
        path = make_shortcut_path("scp_bound_rna", "location[0]", entity_id=make_bound_entity_id(child.id, entry.id))
        add_shortcut(root_obj, "Child X", "SCP", child.id, path)
        new_parent_id = copy_scp_subtree(root_obj, bpy.context.scene, parent.id, [child.id])
        new_child = next(item for item in root_obj.af_scp_system.scps if item.parent_id == new_parent_id)
        new_fiber = next(item for item in root_obj.af_vcp_system.fibers if item.id != fib.id)
        self.assertEqual(({new_fiber.a_parent_id, new_fiber.b_parent_id}, new_child.id), ({new_parent_id, new_child.id}, new_child.id))
        self.assertEqual((root_obj.af_vcp_system.muscles[-1].fiber_refs[0].fiber_id, root_obj.af_vcp_system.blobs[-1].attach_target_id), (new_fiber.id, root_obj.af_vcp_system.muscles[-1].id))
        self.assertEqual((root_obj.af_shortcut_system.shortcuts[-1].owner_id, find_scp_by_id(root_obj, new_parent_id).id, blob.attach_target_id), (new_child.id, new_parent_id, muscle.id))
