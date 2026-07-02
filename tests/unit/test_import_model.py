from pathlib import Path
import importlib.util
import sys
import unittest

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _support import ensure_import_path

ensure_import_path()


def _load_model():
    path = ADDON_ROOT / "core" / "importing" / "model.py"
    spec = importlib.util.spec_from_file_location("import_model_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PackageSnapshot = _load_model().PackageSnapshot


class ImportModelTests(unittest.TestCase):
    def test_package_snapshot_rehydrates_nested_items(self):
        data = _snapshot_dict()
        snap = PackageSnapshot.from_dict(data)
        self.assertEqual((snap.scps[0].bound_objects[0].bound_id, snap.fibers[0].touches[0].parent_id), ("OBJ_1", "S1"))
        self.assertEqual((snap.muscles[0].fiber_ids[0], snap.shortcuts[0].owner_type, snap.shortcuts[0].vector_mode, snap.shortcuts[0].owner_backsolve), ("F1", "SCP", "DEFAULT", False))
        item = snap.shortcuts[0].overrides[0]
        self.assertEqual((item.target_scp_id, item.parent_anchor_mode, item.follow_rotation_mode, item.rotation_strategy), ("S1", "OBJECT_ORIGIN", "KEEP", "KEEP"))
        self.assertEqual((snap.fibers[0].driver_fiber_id, snap.fibers[0].loop_anchors[0].parent_id, snap.fibers[0].loop_profile_keys[0].props["delta_u"]), ("F0", "S1", 0.1))
        self.assertEqual(snap.fibers[0].touches[0].props["normal_offset"], 0.25)

    def test_package_snapshot_defaults_missing_owner_backsolve_to_true(self):
        data = _snapshot_dict()
        data["shortcuts"][0].pop("owner_backsolve")
        self.assertTrue(PackageSnapshot.from_dict(data).shortcuts[0].owner_backsolve)


def _snapshot_dict():
    return {
        "root_name": "AF_ROOT",
        "scps": [{"source_id": "S1", "name": "Arm", "parent_id": "", "props": {}, "bound_objects": [{"bound_id": "OBJ_1", "label": "Arm", "object_name": "ArmObj"}]}],
        "fibers": [{"source_id": "F1", "name": "F1", "props": {"topology_mode": "LOOP", "collision_margin": 0.2, "damping": 0.3, "guide_stiffness": 0.4}, "a_parent_id": "S1", "b_parent_id": "S2", "muscle_id": "", "driver_fiber_id": "F0", "touches": [{"parent_id": "S1", "props": {"normal_offset": 0.25}}], "loop_anchors": [{"parent_id": "S1", "props": {"attach_param": "RAW"}}], "loop_profile_keys": [{"props": {"t": 0.25, "delta_u": 0.1, "delta_v": -0.2}}]}],
        "muscles": [{"source_id": "M1", "name": "M1", "props": {}, "fiber_ids": ["F1"]}],
        "blobs": [{"source_id": "B1", "name": "B1", "props": {}, "attach_target_type": "MUSCLE", "attach_target_id": "M1", "attach_target_object_name": ""}],
        "shortcuts": [{"name": "X", "owner_type": "SCP", "owner_id": "S1", "data_path": "af://scp_prop/S1/name", "owner_backsolve": False, "overrides": [{"target_scp_id": "S1", "parent_anchor_mode": "OBJECT_ORIGIN", "child_anchor_mode": "KEEP"}]}],
    }
