from pathlib import Path
import os
import sys
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, add_shortcut, capture_mesh_attachment, fiber, find_flagged, mesh_object, reset_scene, root, scp_with_object, select_only, temp_blend_path
from anthroforge.core.id_utils import next_prefixed_id
from anthroforge.core.importing.extract import root_snapshot
from anthroforge.core.importing.service import import_package_from_blend, import_scp_diff_from_blend, import_vcp_from_blend
from anthroforge.core.shortcuts import upsert_override
from anthroforge.core.shortcuts.path_codec import make_bound_entity_id, make_shortcut_path
from anthroforge.core.scp_runtime.prop_update_guard import set_parent_id_raw
from anthroforge.core.scp_runtime.runtime_state import set_mirror_effective_axis, set_mirror_source_id, set_mirror_status
from anthroforge.core.utils import get_af_root
from anthroforge.core.vcp.runtime_state import set_fiber_not_converged, set_muscle_inflation_ctrl_world


def _muscle(root_obj, fiber_id):
    item = root_obj.af_vcp_system.muscles.add()
    item.id = next_prefixed_id(root_obj.af_vcp_system.muscles, "MUSCLE")
    item.name = item.id
    item.inflation_mode = "DISTRIBUTED"
    item.fiber_refs.add().fiber_id = fiber_id
    return item


def _blob(root_obj, muscle_id):
    item = root_obj.af_vcp_system.blobs.add()
    item.id = next_prefixed_id(root_obj.af_vcp_system.blobs, "BLOB")
    item.name = item.id
    item.attach_target_type, item.attach_target_id = "MUSCLE", muscle_id
    return item


def _quad_mesh_object(name):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _source_vcp_file():
    snapshot, _right = _source_snapshot()
    path = temp_blend_path()
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return path, (snapshot.scps[0].source_id, snapshot.scps[1].source_id)


def _source_scp_diff_file():
    root_obj = root()
    parent = scp_with_object(root_obj, "ParentSource", mesh_object("ParentSource"))
    child = scp_with_object(root_obj, "ChildSource", mesh_object("ChildSource", (2.0, 0.0, 0.0)))
    set_parent_id_raw(child, parent.id)
    item = fiber(root_obj, parent.id, child.id)
    item.a_attach_param = capture_mesh_attachment(root_obj, parent, 0)
    item.b_attach_param = capture_mesh_attachment(root_obj, child, 0)
    add_shortcut(root_obj, "Child X", "SCP", child.id, f'bpy.data.objects["{child.transform_object_ref.name}"].location[0]')
    path = temp_blend_path()
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return path, (parent.id, child.id)


def _matching_target():
    root_obj = root()
    left = scp_with_object(root_obj, "LeftTarget", mesh_object("LeftTarget"))
    right = scp_with_object(root_obj, "RightTarget", mesh_object("RightTarget", (2.0, 0.0, 0.0)))
    return root_obj, left, right


def _scp_diff_target(parent_id):
    root_obj = root()
    root_obj.af_draft_skin_settings.collagen_depth_percent = 0.25
    parent = scp_with_object(root_obj, "ParentTarget", mesh_object("ParentTarget"))
    return root_obj, parent


def _vcp_target():
    root_obj, left, right = _matching_target()
    root_obj.af_draft_skin_settings.collagen_depth_percent = 0.35
    return root_obj, left, right, fiber(root_obj, left.id, right.id)


def _source_snapshot():
    root_obj = root()
    root_obj.af_draft_skin_settings.collagen_depth_percent = 1.25
    left = scp_with_object(root_obj, "Left", mesh_object("Left"))
    right = scp_with_object(root_obj, "Right", mesh_object("Right", (2.0, 0.0, 0.0)))
    left.mirror_enabled, left.mirror_axis = True, "Y"
    set_mirror_status(left, "SOURCE")
    set_mirror_source_id(right, left.id)
    set_mirror_effective_axis(right, "Y")
    item = fiber(root_obj, left.id, right.id)
    item.a_attach_param = capture_mesh_attachment(root_obj, left, 0)
    item.b_attach_param = capture_mesh_attachment(root_obj, right, 0)
    touch = item.mid_touches.add()
    touch.parent_id = left.id
    touch.attach_param = capture_mesh_attachment(root_obj, left, 0)
    touch.normal_offset = 0.125
    set_fiber_not_converged(item, True)
    muscle = _muscle(root_obj, item.id)
    item.muscle_id = muscle.id
    set_muscle_inflation_ctrl_world(muscle, (7.0, 8.0, 9.0))
    _blob(root_obj, muscle.id)
    row = add_shortcut(root_obj, "Right X", "SCP", right.id, f'bpy.data.objects["{right.transform_object_ref.name}"].location[0]')
    row.owner_backsolve = False
    upsert_override(row, left.id, "OBJECT_ORIGIN", "KEEP")
    return root_snapshot(root_obj), right




class ImportPackageE2ETests(BlenderTestCase):
    def test_import_package_remaps_relationships_and_shortcuts(self):
        snapshot, right = _source_snapshot()
        path = temp_blend_path()
        self.addCleanup(lambda: os.remove(path) if os.path.exists(path) else None)
        bpy.ops.wm.save_as_mainfile(filepath=path)
        self.assertNotIn("not_converged", snapshot.fibers[0].props)
        self.assertIn("mirror_enabled", snapshot.scps[0].props)
        self.assertNotIn("mirror_status", snapshot.scps[0].props)
        self.assertNotIn("mirror_source_id", snapshot.scps[1].props)
        self.assertNotIn("mirror_effective_axis", snapshot.scps[1].props)
        self.assertIn("attach_follow_rotation", snapshot.scps[0].props)
        self.assertNotIn("attach_initialized", snapshot.scps[0].props)
        self.assertNotIn("attach_child_origin_local", snapshot.scps[0].props)
        self.assertEqual(snapshot.muscles[0].props["inflation_mode"], "DISTRIBUTED")
        self.assertNotIn("inflation_ctrl_world", snapshot.muscles[0].props)
        reset_scene()
        scp_with_object(root(), "Existing", mesh_object("Existing"))
        result = import_package_from_blend(path, bpy.context)
        root_obj = get_af_root(bpy.context.scene)
        imported = {scp.name: scp for scp in root_obj.af_scp_system.scps if scp.name in {"Left", "Right"}}
        fiber_item = root_obj.af_vcp_system.fibers[-1]
        self.assertEqual((result.scp_count, result.fiber_count, result.muscle_count, result.blob_count, result.shortcut_count), (2, 1, 1, 1, 1))
        self.assertEqual({fiber_item.a_parent_id, fiber_item.b_parent_id}, {imported["Left"].id, imported["Right"].id})
        self.assertEqual((root_obj.af_vcp_system.muscles[-1].fiber_refs[0].fiber_id, root_obj.af_vcp_system.blobs[-1].attach_target_id), (fiber_item.id, root_obj.af_vcp_system.muscles[-1].id))
        self.assertEqual(root_obj.af_vcp_system.muscles[-1].inflation_mode, "DISTRIBUTED")
        self.assertEqual((len(fiber_item.mid_touches), round(fiber_item.mid_touches[0].normal_offset, 4)), (1, 0.125))
        self.assertEqual((root_obj.af_shortcut_system.shortcuts[-1].owner_id, imported["Right"].id in root_obj.af_shortcut_system.shortcuts[-1].data_path), (imported["Right"].id, True))
        self.assertFalse(root_obj.af_shortcut_system.shortcuts[-1].owner_backsolve)
        self.assertEqual(root_obj.af_shortcut_system.shortcuts[-1].overrides[0].target_scp_id, imported["Left"].id)
        self.assertIsNotNone(find_flagged("af_fiber_proxy", fiber_item.id, "af_fiber_id"))
        self.assertIsNotNone(find_flagged("af_muscle_proxy", root_obj.af_vcp_system.muscles[-1].id, "af_muscle_id"))
        self.assertIsNotNone(find_flagged("af_blob_proxy", root_obj.af_vcp_system.blobs[-1].id, "af_blob_id"))
        self.assertAlmostEqual(root_obj.af_draft_skin_settings.collagen_depth_percent, 1.25)

    def test_import_scp_diff_imports_only_missing_scps(self):
        path, (parent_id, child_id) = _source_scp_diff_file()
        self.addCleanup(lambda: os.remove(path) if os.path.exists(path) else None)
        reset_scene()
        root_obj, parent = _scp_diff_target(parent_id)
        self.assertEqual(parent.id, parent_id)
        self._assert_scp_diff_import(root_obj, path, parent_id, child_id)
        result = import_scp_diff_from_blend(path, bpy.context)
        self.assertEqual((result.scp_count, result.fiber_count, result.shortcut_count), (0, 0, 0))
        self.assertAlmostEqual(root_obj.af_draft_skin_settings.collagen_depth_percent, 0.25)

    def _assert_scp_diff_import(self, root_obj, path, parent_id, child_id):
        with patch("anthroforge.core.importing.merge.schedule_sync_from_dirty_hints") as schedule:
            result = import_scp_diff_from_blend(path, bpy.context)
        child = next(scp for scp in root_obj.af_scp_system.scps if scp.id == child_id)
        shortcut = root_obj.af_shortcut_system.shortcuts[-1]
        self.assertEqual((result.scp_count, result.fiber_count, result.shortcut_count), (1, 1, 1))
        self.assertEqual((child.parent_id, len(root_obj.af_scp_system.scps)), (parent_id, 2))
        self.assertEqual((root_obj.af_vcp_system.fibers[-1].a_parent_id, root_obj.af_vcp_system.fibers[-1].b_parent_id), (parent_id, child_id))
        self.assertEqual((shortcut.owner_id, child_id in shortcut.data_path), (child_id, True))
        self.assertIn(child_id, schedule.call_args.kwargs["dirty_hints"]["SCP"])
        self.assertFalse(schedule.call_args.kwargs["dirty_hints"].full)

    def test_import_vcp_uses_matching_target_scp_ids_and_topology(self):
        path, source_ids = _source_vcp_file()
        self.addCleanup(lambda: os.remove(path) if os.path.exists(path) else None)
        reset_scene()
        root_obj, left, right, existing = _vcp_target()
        self._assert_vcp_import(root_obj, left, right, existing, path, source_ids)
        self.assertAlmostEqual(root_obj.af_draft_skin_settings.collagen_depth_percent, 0.35)

    def _assert_vcp_import(self, root_obj, left, right, existing, path, source_ids):
        with patch("anthroforge.core.importing.service.append_stage_root", side_effect=AssertionError("append")), patch(
            "anthroforge.core.importing.vcp.schedule_sync_from_dirty_hints"
        ) as schedule:
            result = import_vcp_from_blend(path, bpy.context)
        imported_fiber = root_obj.af_vcp_system.fibers[-1]
        imported_muscle = root_obj.af_vcp_system.muscles[-1]
        self.assertEqual((left.id, right.id), source_ids)
        self.assertEqual((result.scp_count, result.fiber_count, result.muscle_count, result.blob_count), (0, 1, 1, 1))
        self.assertEqual((len(root_obj.af_scp_system.scps), existing.id, imported_fiber.id), (2, "FIBER_1", "FIBER_2"))
        self.assertEqual((imported_fiber.a_parent_id, imported_fiber.b_parent_id), source_ids)
        self.assertEqual((imported_muscle.fiber_refs[0].fiber_id, imported_fiber.muscle_id), (imported_fiber.id, imported_muscle.id))
        self.assertEqual(root_obj.af_vcp_system.blobs[-1].attach_target_id, imported_muscle.id)
        self.assertEqual(schedule.call_count, 1)
        self.assertIn(imported_fiber.id, schedule.call_args.kwargs["dirty_hints"]["FIBER"])
        self.assertFalse(schedule.call_args.kwargs["dirty_hints"].full)

    def test_import_vcp_skips_mismatched_scp_topology(self):
        path, _source_ids = _source_vcp_file()
        self.addCleanup(lambda: os.remove(path) if os.path.exists(path) else None)
        reset_scene()
        root_obj = root()
        scp_with_object(root_obj, "LeftTarget", mesh_object("LeftTarget"))
        scp_with_object(root_obj, "RightTarget", _quad_mesh_object("RightTarget"))
        result = import_vcp_from_blend(path, bpy.context)
        self.assertEqual((result.fiber_count, result.muscle_count, result.blob_count), (0, 0, 0))
        self.assertEqual((len(root_obj.af_vcp_system.fibers), bool(result.warnings)), (0, True))

