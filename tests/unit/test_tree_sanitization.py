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

from core.scp_runtime.runtime_state import attach_initialized, set_attach_initialized
from core.scp_runtime.tree import children_depth_order, sanitize_parent_links


def scp(sid, parent_id="", ready=True):
    item = SimpleNamespace(id=sid, parent_id=parent_id)
    set_attach_initialized(item, ready)
    return item


def root(*scps):
    return SimpleNamespace(af_scp_system=SimpleNamespace(scps=list(scps)))


class TreeSanitizationTests(unittest.TestCase):
    def test_sanitize_parent_links_clears_cycles_and_missing_parents(self):
        target = root(scp("S1", "S2"), scp("S2", "S1"), scp("S3", "MISS"))
        changed, _ = sanitize_parent_links(target, {item.id: item for item in target.af_scp_system.scps})
        state = {item.id: (item.parent_id, attach_initialized(item)) for item in target.af_scp_system.scps}
        self.assertEqual(changed, {"S1", "S2", "S3"})
        self.assertEqual(state, {"S1": ("", False), "S2": ("", False), "S3": ("", False)})

    def test_children_depth_order_keeps_ancestors_first(self):
        items = {"S1": scp("S1"), "S2": scp("S2", "S1"), "S3": scp("S3", "S2")}
        ordered = children_depth_order(items)
        self.assertEqual(ordered, ["S1", "S2", "S3"])
