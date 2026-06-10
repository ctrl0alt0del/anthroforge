from pathlib import Path
import os
import sys

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, add_shortcut, fiber, find_flagged, mesh_object, reset_scene, root, scp_with_object, temp_blend_path
from anthroforge.core.id_utils import next_prefixed_id
from anthroforge.core.importing.extract import root_snapshot
from anthroforge.core.importing.service import import_package_from_blend
from anthroforge.core.shortcuts.path_codec import make_bound_entity_id, make_shortcut_path
from anthroforge.core.scp_runtime.runtime_state import set_mirror_effective_axis, set_mirror_source_id, set_mirror_status
from anthroforge.core.utils import get_af_root
from anthroforge.core.vcp.runtime_state import set_fiber_not_converged, set_muscle_inflation_ctrl_world


def _muscle(root_obj, fiber_id):
    item = root_obj.af_vcp_system.muscles.add()
    item.id = next_prefixed_id(root_obj.af_vcp_system.muscles, "MUSCLE")
    item.name = item.id
    item.fiber_refs.add().fiber_id = fiber_id
    return item


def _blob(root_obj, muscle_id):
    item = root_obj.af_vcp_system.blobs.add()
    item.id = next_prefixed_id(root_obj.af_vcp_system.blobs, "BLOB")
    item.name = item.id
    item.attach_target_type, item.attach_target_id = "MUSCLE", muscle_id
    return item


def _source_snapshot():
    root_obj = root()
    left = scp_with_object(root_obj, "Left", mesh_object("Left"))
    right = scp_with_object(root_obj, "Right", mesh_object("Right", (2.0, 0.0, 0.0)))
    left.mirror_enabled, left.mirror_axis = True, "Y"
    set_mirror_status(left, "SOURCE")
    set_mirror_source_id(right, left.id)
    set_mirror_effective_axis(right, "Y")
    item = fiber(root_obj, left.id, right.id)
    item.a_attach_param, item.b_attach_param = "A", "B"
    set_fiber_not_converged(item, True)
    muscle = _muscle(root_obj, item.id)
    item.muscle_id = muscle.id
    set_muscle_inflation_ctrl_world(muscle, (7.0, 8.0, 9.0))
    _blob(root_obj, muscle.id)
    add_shortcut(root_obj, "Right X", "SCP", right.id, f'bpy.data.objects["{right.transform_object_ref.name}"].location[0]')
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
        self.assertEqual((root_obj.af_shortcut_system.shortcuts[-1].owner_id, imported["Right"].id in root_obj.af_shortcut_system.shortcuts[-1].data_path), (imported["Right"].id, True))
        self.assertIsNotNone(find_flagged("af_fiber_proxy", fiber_item.id, "af_fiber_id"))
        self.assertIsNotNone(find_flagged("af_muscle_proxy", root_obj.af_vcp_system.muscles[-1].id, "af_muscle_id"))
        self.assertIsNotNone(find_flagged("af_blob_proxy", root_obj.af_vcp_system.blobs[-1].id, "af_blob_id"))
