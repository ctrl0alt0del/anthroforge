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

from core.shortcuts import session_state


class ShortcutSessionStateTests(unittest.TestCase):
    def setUp(self):
        session_state.reset_shortcut_runtime_state()

    def test_reset_clears_suppression_session_and_cache(self):
        session_state.suppress_next_depsgraph_ids({"SCP_1"})
        session_state.begin_override_session("SCP_1", "FACE_CENTER", "KEEP")
        session_state.store_override_runtime("K1", {"SCP_1": ("KEEP",)}, {"SCP_1": {"value": 1}})
        session_state.reset_shortcut_runtime_state()
        owner = SimpleNamespace(id="SCP_1")
        self.assertEqual(session_state.consume_suppressed_ids({"SCP_1"}), {"SCP_1"})
        self.assertEqual(session_state.active_parent_override(owner), "")
        self.assertEqual(session_state.cached_override_runtime("K1", {"SCP_1": ("KEEP",)}), {})


if __name__ == "__main__":
    unittest.main()
