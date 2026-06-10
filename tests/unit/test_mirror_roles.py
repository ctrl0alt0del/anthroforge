from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _support import ensure_import_path, install_fake_modules

ensure_import_path()
install_fake_modules()

from core.scp_runtime.mirror_roles import apply_scp_mirror_roles
from core.scp_runtime.runtime_state import mirror_effective_axis, mirror_source_id, mirror_status, reset_mirror_runtime


def scp(sid, parent_id="", enabled=False, inherit=True, axis="X"):
    item = SimpleNamespace(
        id=sid,
        parent_id=parent_id,
        mirror_enabled=enabled,
        mirror_inherit_parent=inherit,
        mirror_axis=axis,
    )
    reset_mirror_runtime(item)
    return item


class MirrorRoleTests(unittest.TestCase):
    def test_mirror_source_propagates_to_children(self):
        root = SimpleNamespace(af_scp_system=SimpleNamespace(scps=[scp("S1", enabled=True, axis="Y"), scp("S2", "S1"), scp("S3", "S2", inherit=False)]))
        changed = apply_scp_mirror_roles(root)
        items = {item.id: item for item in root.af_scp_system.scps}
        self.assertEqual(mirror_status(items["S1"]), "SOURCE")
        self.assertEqual(mirror_source_id(items["S2"]), "S1")
        self.assertEqual(mirror_effective_axis(items["S2"]), "Y")
        self.assertEqual(mirror_status(items["S3"]), "NONE")
        self.assertIn("S2", changed)
