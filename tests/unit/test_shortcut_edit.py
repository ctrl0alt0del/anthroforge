from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _support import ensure_import_path, install_fake_modules

ensure_import_path()
install_fake_modules()

from app.use_cases import shortcut_edit as edit
from core.shortcuts import has_override, remap_overrides


class ShortcutEditTests(unittest.TestCase):
    def test_apply_shortcut_proxy_ignores_locked_shortcut(self):
        shortcut = SimpleNamespace(proxy_sync_lock=True)
        with patch("app.use_cases.shortcut_edit.resolve_shortcut") as resolve:
            self.assertFalse(edit.apply_shortcut_proxy(SimpleNamespace(), shortcut))
        resolve.assert_not_called()

    def test_apply_shortcut_proxy_writes_enum_value(self):
        shortcut = SimpleNamespace(proxy_sync_lock=False, owner_type="BLOB", owner_id="B1", data_path="PATH", proxy_enum="OPT_B")
        target = SimpleNamespace(owner=object(), prop_name="mode", index=-1, value_type="ENUM", array_length=0)
        with patch("app.use_cases.shortcut_edit.root_for_context", return_value=object()):
            with patch("app.use_cases.shortcut_edit.resolve_shortcut", return_value=target):
                with patch("app.use_cases.shortcut_edit.write_target_value") as write:
                    self.assertTrue(edit.apply_shortcut_proxy(SimpleNamespace(), shortcut))
        write.assert_called_once_with(target, "OPT_B")

    def test_apply_shortcut_proxy_writes_whole_array_value(self):
        shortcut = SimpleNamespace(proxy_sync_lock=False, owner_type="BLOB", owner_id="B1", data_path="PATH", proxy_float_vec=(1.0, 2.0, 3.0))
        target = SimpleNamespace(owner=object(), prop_name="location", index=-1, value_type="FLOAT", array_length=3)
        with patch("app.use_cases.shortcut_edit.root_for_context", return_value=object()):
            with patch("app.use_cases.shortcut_edit.resolve_shortcut", return_value=target):
                with patch("app.use_cases.shortcut_edit.write_target_value") as write:
                    self.assertTrue(edit.apply_shortcut_proxy(SimpleNamespace(), shortcut))
        write.assert_called_once_with(target, (1.0, 2.0, 3.0))

    def test_apply_shortcut_proxy_builds_scp_session_for_indexed_array(self):
        root = SimpleNamespace()
        shortcut = SimpleNamespace(proxy_sync_lock=False, owner_type="SCP", owner_id="P1", data_path="PATH", proxy_float_vec=(0.0, 4.5, 0.0))
        target = SimpleNamespace(owner=object(), prop_name="location", index=1, value_type="FLOAT", array_length=3)
        ctx = SimpleNamespace()
        with patch("app.use_cases.shortcut_edit.root_for_context", return_value=root):
            with patch("app.use_cases.shortcut_edit.resolve_shortcut", return_value=target):
                with patch("app.use_cases.shortcut_edit.selected_scp_id", return_value="C1"):
                    with patch("app.use_cases.shortcut_edit.shortcut_relation", return_value="ANCESTOR"):
                        with patch("app.use_cases.shortcut_edit.override_modes", return_value=("OBJECT_ORIGIN", "OBJECT_ORIGIN")):
                            with patch("app.use_cases.shortcut_edit.find_scp_by_id", return_value=SimpleNamespace(parent_id="P1")):
                                    with patch("app.use_cases.shortcut_edit.write_target_value") as write:
                                        with patch("app.use_cases.shortcut_edit.begin_override_session") as begin:
                                            with patch("app.use_cases.shortcut_edit.suppress_next_depsgraph_ids") as suppress:
                                                with patch("app.use_cases.shortcut_edit.clear_override_session") as clear:
                                                    with patch("app.use_cases.shortcut_edit._dirty_hints_for", return_value=lambda _et, ids: set(ids)) as dirty:
                                                        with patch("app.use_cases.shortcut_edit._sync_context", return_value=lambda *args, **kwargs: sync(*args, **kwargs)):
                                                            sync = Recorder()
                                                            self.assertTrue(edit.apply_shortcut_proxy(ctx, shortcut))
        write.assert_called_once_with(target, 4.5)
        begin.assert_called_once_with("C1", "OBJECT_ORIGIN", "OBJECT_ORIGIN")
        suppress.assert_called_once_with({"P1"})
        dirty.assert_called_once_with()
        self.assertEqual(sync.calls, [((ctx,), {"dirty_hints": {"P1", "C1"}, "source": "shortcut", "event_type": "UPDATE", "payload": {"scp_apply_parent_ids": ["P1"], "scp_recapture_ids": ["C1"]}})])
        clear.assert_called_once()

    def test_override_helpers_return_default_and_drop_orphans(self):
        src = SimpleNamespace(overrides=OverrideCollection([override("S1", "OBJECT_ORIGIN"), override("S9", "KEEP", "OBJECT_ORIGIN")]))
        dst = SimpleNamespace(overrides=OverrideCollection())
        self.assertFalse(has_override(SimpleNamespace(overrides=[]), "S1"))
        remap_overrides(dst, src, {"S1": "S2"})
        self.assertEqual([(item.target_scp_id, item.parent_anchor_mode, item.child_anchor_mode) for item in dst.overrides], [("S2", "OBJECT_ORIGIN", "KEEP")])


class OverrideCollection(list):
    def add(self):
        item = override("")
        self.append(item)
        return item

    def remove(self, index):
        self.pop(index)


def override(target_scp_id, parent_mode="KEEP", child_mode="KEEP"):
    return SimpleNamespace(target_scp_id=target_scp_id, parent_anchor_mode=parent_mode, child_anchor_mode=child_mode)


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))


if __name__ == "__main__":
    unittest.main()
