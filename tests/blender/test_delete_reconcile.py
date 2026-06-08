from pathlib import Path
import sys

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, empty_object, fiber, root, scp_with_object
from core.scp_runtime.delete import delete_scp
from core.id_utils import next_prefixed_id
from core.visualization.delete_reconcile import cleanup_scp_dependents, reconcile_deleted_entities


def _muscle(root_obj, fiber_id):
    item = root_obj.af_vcp_system.muscles.add()
    item.id = next_prefixed_id(root_obj.af_vcp_system.muscles, "MUSCLE")
    item.name = item.id
    item.fiber_refs.add().fiber_id = fiber_id
    return item


def _blob(root_obj, target_type, target_id):
    item = root_obj.af_vcp_system.blobs.add()
    item.id = next_prefixed_id(root_obj.af_vcp_system.blobs, "BLOB")
    item.name = item.id
    item.attach_target_type, item.attach_target_id = target_type, target_id
    return item


class DeleteReconcileTests(BlenderTestCase):
    def test_delete_scp_removes_orphan_fibers(self):
        root_obj = root()
        left = scp_with_object(root_obj, "Left", empty_object("Left"))
        right = scp_with_object(root_obj, "Right", empty_object("Right"))
        item = fiber(root_obj, left.id, right.id)
        self.assertEqual((len(root_obj.af_scp_system.scps), len(root_obj.af_vcp_system.fibers)), (2, 1))
        self.assertTrue(delete_scp(root_obj, bpy.context.scene, left.id))
        self.assertEqual(len(root_obj.af_scp_system.scps), 1)
        self.assertEqual((len(root_obj.af_vcp_system.fibers), item.id in {f.id for f in root_obj.af_vcp_system.fibers}), (0, False))

    def test_reconcile_removed_muscles_and_blobs_clears_active_refs(self):
        root_obj = root()
        left = scp_with_object(root_obj, "Left", empty_object("Left"))
        right = scp_with_object(root_obj, "Right", empty_object("Right"))
        item = fiber(root_obj, left.id, right.id)
        muscle = _muscle(root_obj, item.id)
        item.muscle_id = muscle.id
        blob = _blob(root_obj, "MUSCLE", muscle.id)
        root_obj.af_vcp_system.active_vcp_type, root_obj.af_vcp_system.active_vcp_id = "MUSCLE", muscle.id
        reconcile_deleted_entities(root_obj, bpy.context.scene, {("MUSCLE", muscle.id, "BASE"), ("BLOB", blob.id, "PROXY")})
        self.assertEqual((len(root_obj.af_vcp_system.muscles), len(root_obj.af_vcp_system.blobs), item.muscle_id), (0, 0, ""))
        self.assertEqual((root_obj.af_vcp_system.active_vcp_type, root_obj.af_vcp_system.active_vcp_id), ("NONE", ""))

    def test_cleanup_dependents_clears_invalid_parent_and_blob_target(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Solo", empty_object("Solo"))
        blob = _blob(root_obj, "SCP", scp.id)
        blob.attach_target_id, scp.parent_id = "MISSING", "MISSING"
        root_obj.af_scp_system.active_scp_index = 9
        changed = cleanup_scp_dependents(root_obj)
        self.assertEqual((changed, scp.parent_id, blob.attach_target_id), (True, "", ""))
        self.assertEqual(root_obj.af_scp_system.active_scp_index, 0)
