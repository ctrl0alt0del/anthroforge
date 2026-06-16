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

    def test_apply_shortcut_value_expands_uniform_vector(self):
        shortcut = SimpleNamespace(proxy_sync_lock=False, owner_type="BLOB", owner_id="B1", data_path="PATH", vector_mode="UNIFORM")
        target = SimpleNamespace(owner=object(), prop_name="scale", index=-1, value_type="FLOAT", array_length=3, subtype="XYZ")
        with patch("app.use_cases.shortcut_edit.root_for_context", return_value=object()):
            with patch("app.use_cases.shortcut_edit.resolve_shortcut", return_value=target):
                with patch("app.use_cases.shortcut_edit.write_target_value") as write:
                    self.assertTrue(edit.apply_shortcut_value(SimpleNamespace(), shortcut, 2.5))
        write.assert_called_once_with(target, (2.5, 2.5, 2.5))

    def test_apply_shortcut_proxy_builds_scp_session_for_indexed_array(self):
        root = SimpleNamespace()
        shortcut = SimpleNamespace(
            proxy_sync_lock=False, owner_type="SCP", owner_id="P1", data_path="PATH",
            proxy_float_vec=(0.0, 4.5, 0.0),
            overrides=[override("C1", "OBJECT_ORIGIN", "OBJECT_ORIGIN", "DISABLED", "KEEP"), override("S9", "OBJECT_ORIGIN")],
        )
        target = SimpleNamespace(owner=object(), prop_name="location", index=1, value_type="FLOAT", array_length=3)
        ctx = SimpleNamespace()
        with patch("app.use_cases.shortcut_edit.root_for_context", return_value=root):
            with patch("app.use_cases.shortcut_edit.resolve_shortcut", return_value=target):
                with patch("app.use_cases.shortcut_edit.shortcut_relation", side_effect=lambda _root, _row, sid: "ANCESTOR" if sid == "C1" else "UNRELATED"):
                    with patch("app.use_cases.shortcut_edit.find_scp_by_id", side_effect=lambda _root, sid: SimpleNamespace(parent_id="P1") if sid in {"C1", "S9"} else None):
                        with patch("app.use_cases.shortcut_edit.write_target_value") as write:
                            with patch("app.use_cases.shortcut_edit.begin_override_sessions") as begin:
                                with patch("app.use_cases.shortcut_edit.suppress_next_depsgraph_ids") as suppress:
                                    with patch("app.use_cases.shortcut_edit.clear_override_session") as clear:
                                        with patch("app.use_cases.shortcut_edit._dirty_hints_for", return_value=lambda _et, ids: set(ids)) as dirty:
                                            with patch("app.use_cases.shortcut_edit._sync_context", return_value=lambda *args, **kwargs: sync(*args, **kwargs)):
                                                sync = Recorder()
                                                self.assertTrue(edit.apply_shortcut_proxy(ctx, shortcut))
        write.assert_called_once_with(target, 4.5)
        begin.assert_called_once_with({"C1": ("OBJECT_ORIGIN", "OBJECT_ORIGIN", "DISABLED", "KEEP")})
        suppress.assert_called_once_with({"P1", "C1"})
        dirty.assert_called_once_with()
        self.assertEqual(sync.calls, [((ctx,), {"dirty_hints": {"P1", "C1"}, "source": "shortcut", "event_type": "UPDATE", "payload": {"scp_apply_parent_ids": ["P1"], "scp_recapture_ids": []}})])
        clear.assert_called_once()

    def test_apply_shortcut_proxy_skips_recapture_for_follow_rotation_override(self):
        root, ctx = SimpleNamespace(), SimpleNamespace()
        shortcut = SimpleNamespace(proxy_sync_lock=False, owner_type="SCP", owner_id="P1", data_path="PATH", proxy_float=2.5, overrides=[override("C1", follow_mode="DISABLED")])
        target = SimpleNamespace(owner=object(), prop_name="location", index=-1, value_type="FLOAT", array_length=0)
        with patch("app.use_cases.shortcut_edit.root_for_context", return_value=root), patch("app.use_cases.shortcut_edit.resolve_shortcut", return_value=target), patch("app.use_cases.shortcut_edit.shortcut_relation", return_value="ANCESTOR"), patch("app.use_cases.shortcut_edit.find_scp_by_id", return_value=SimpleNamespace(parent_id="P1")), patch("app.use_cases.shortcut_edit.write_target_value"), patch("app.use_cases.shortcut_edit.begin_override_sessions") as begin, patch("app.use_cases.shortcut_edit.suppress_next_depsgraph_ids"), patch("app.use_cases.shortcut_edit.clear_override_session"), patch("app.use_cases.shortcut_edit._dirty_hints_for", return_value=lambda _et, ids: set(ids)), patch("app.use_cases.shortcut_edit._sync_context", return_value=lambda *args, **kwargs: sync(*args, **kwargs)):
            sync = Recorder()
            self.assertTrue(edit.apply_shortcut_proxy(ctx, shortcut))
        begin.assert_called_once_with({"C1": ("KEEP", "KEEP", "DISABLED", "KEEP")})
        self.assertEqual(sync.calls, [((ctx,), {"dirty_hints": {"P1"}, "source": "shortcut", "event_type": "UPDATE", "payload": {"scp_apply_parent_ids": ["P1"], "scp_recapture_ids": []}})])

    def test_apply_shortcut_proxy_recaptures_for_rotation_strategy_override(self):
        root, ctx = SimpleNamespace(), SimpleNamespace()
        shortcut = SimpleNamespace(proxy_sync_lock=False, owner_type="SCP", owner_id="P1", data_path="PATH", proxy_float=2.5, overrides=[override("C1", strategy="DEFORMATION_FLOW")])
        target = SimpleNamespace(owner=object(), prop_name="location", index=-1, value_type="FLOAT", array_length=0)
        with patch("app.use_cases.shortcut_edit.root_for_context", return_value=root), patch("app.use_cases.shortcut_edit.resolve_shortcut", return_value=target), patch("app.use_cases.shortcut_edit.shortcut_relation", return_value="ANCESTOR"), patch("app.use_cases.shortcut_edit.find_scp_by_id", return_value=SimpleNamespace(parent_id="P1")), patch("app.use_cases.shortcut_edit.write_target_value"), patch("app.use_cases.shortcut_edit.begin_override_sessions"), patch("app.use_cases.shortcut_edit.suppress_next_depsgraph_ids"), patch("app.use_cases.shortcut_edit.clear_override_session"), patch("app.use_cases.shortcut_edit._dirty_hints_for", return_value=lambda _et, ids: set(ids)), patch("app.use_cases.shortcut_edit._sync_context", return_value=lambda *args, **kwargs: sync(*args, **kwargs)):
            sync = Recorder()
            self.assertTrue(edit.apply_shortcut_proxy(ctx, shortcut))
        self.assertEqual(sync.calls, [((ctx,), {"dirty_hints": {"P1", "C1"}, "source": "shortcut", "event_type": "UPDATE", "payload": {"scp_apply_parent_ids": ["P1"], "scp_recapture_ids": []}})])

    def test_apply_shortcut_proxy_treats_authored_override_values_as_keep(self):
        root, ctx = SimpleNamespace(), SimpleNamespace()
        child = SimpleNamespace(parent_id="P1", attach_parent_anchor_mode="SURFACE_NEAREST", attach_child_anchor_mode="FACE_CENTER", attach_follow_rotation=True, attach_tangent_strategy="AUTO")
        shortcut = SimpleNamespace(proxy_sync_lock=False, owner_type="SCP", owner_id="P1", id="K1", data_path="PATH", proxy_float=2.5, overrides=[override("C1", "SURFACE_NEAREST", "FACE_CENTER", "ENABLED", "AUTO")])
        target = SimpleNamespace(owner=object(), prop_name="location", index=-1, value_type="FLOAT", array_length=0)
        with patch("app.use_cases.shortcut_edit.root_for_context", return_value=root), patch("app.use_cases.shortcut_edit.resolve_shortcut", return_value=target), patch("app.use_cases.shortcut_edit.shortcut_relation", return_value="ANCESTOR"), patch("app.use_cases.shortcut_edit.find_scp_by_id", return_value=child), patch("app.use_cases.shortcut_edit.write_target_value"), patch("app.use_cases.shortcut_edit.begin_override_sessions") as begin, patch("app.use_cases.shortcut_edit.suppress_next_depsgraph_ids") as suppress, patch("app.use_cases.shortcut_edit.clear_override_session"), patch("app.use_cases.shortcut_edit._dirty_hints_for", return_value=lambda _et, ids: set(ids)), patch("app.use_cases.shortcut_edit._sync_context", return_value=lambda *args, **kwargs: sync(*args, **kwargs)):
            sync = Recorder()
            self.assertTrue(edit.apply_shortcut_proxy(ctx, shortcut))
        begin.assert_called_once_with({})
        suppress.assert_called_once_with({"P1"})
        self.assertEqual(sync.calls, [((ctx,), {"dirty_hints": {"P1"}, "source": "shortcut", "event_type": "UPDATE", "payload": {"scp_apply_parent_ids": ["P1"], "scp_recapture_ids": []}})])

    def test_apply_shortcut_proxy_reuses_cached_runtime_snapshot(self):
        root, ctx = SimpleNamespace(), SimpleNamespace()
        child = SimpleNamespace(parent_id="P1", attach_parent_anchor_mode="SURFACE_NEAREST", attach_child_anchor_mode="FACE_CENTER", attach_follow_rotation=True, attach_tangent_strategy="AUTO")
        shortcut = SimpleNamespace(proxy_sync_lock=False, owner_type="SCP", owner_id="P1", id="K1", data_path="PATH", proxy_float=2.5, overrides=[override("C1", "OBJECT_ORIGIN", "OBJECT_ORIGIN", "DISABLED", "DEFORMATION_FLOW")])
        target = SimpleNamespace(owner=object(), prop_name="location", index=-1, value_type="FLOAT", array_length=0)
        authored, cached, stored = {"mode": "authored"}, {"mode": "cached"}, {"mode": "stored"}
        with patch("app.use_cases.shortcut_edit.root_for_context", return_value=root), patch("app.use_cases.shortcut_edit.resolve_shortcut", return_value=target), patch("app.use_cases.shortcut_edit.shortcut_relation", return_value="ANCESTOR"), patch("app.use_cases.shortcut_edit.find_scp_by_id", return_value=child), patch("app.use_cases.shortcut_edit.cached_override_runtime", return_value={"C1": cached}), patch("app.use_cases.shortcut_edit.snapshot_attachment_runtime", side_effect=[authored, stored]), patch("app.use_cases.shortcut_edit.restore_attachment_runtime") as restore, patch("app.use_cases.shortcut_edit.store_override_runtime") as cache_store, patch("app.use_cases.shortcut_edit.write_target_value"), patch("app.use_cases.shortcut_edit.begin_override_sessions"), patch("app.use_cases.shortcut_edit.suppress_next_depsgraph_ids"), patch("app.use_cases.shortcut_edit.clear_override_session"), patch("app.use_cases.shortcut_edit._dirty_hints_for", return_value=lambda _et, ids: set(ids)), patch("app.use_cases.shortcut_edit._sync_context", return_value=lambda *args, **kwargs: sync(*args, **kwargs)):
            sync = Recorder()
            self.assertTrue(edit.apply_shortcut_proxy(ctx, shortcut))
        self.assertEqual(sync.calls, [((ctx,), {"dirty_hints": {"P1"}, "source": "shortcut", "event_type": "UPDATE", "payload": {"scp_apply_parent_ids": ["P1"], "scp_recapture_ids": []}})])
        self.assertEqual(restore.call_args_list[0].args, (child, cached))
        self.assertEqual(restore.call_args_list[-1].args, (child, authored))
        cache_store.assert_called_once_with("K1", {"C1": ("OBJECT_ORIGIN", "OBJECT_ORIGIN", "DISABLED", "DEFORMATION_FLOW")}, {"C1": stored})

    def test_override_helpers_return_default_and_drop_orphans(self):
        src = SimpleNamespace(overrides=OverrideCollection([override("S1", "OBJECT_ORIGIN", follow_mode="DISABLED", strategy="DEFORMATION_FLOW"), override("S9", "KEEP", "OBJECT_ORIGIN")]))
        dst = SimpleNamespace(overrides=OverrideCollection())
        self.assertFalse(has_override(SimpleNamespace(overrides=[]), "S1"))
        remap_overrides(dst, src, {"S1": "S2"})
        self.assertEqual([(item.target_scp_id, item.parent_anchor_mode, item.child_anchor_mode, item.follow_rotation_mode, item.rotation_strategy) for item in dst.overrides], [("S2", "OBJECT_ORIGIN", "KEEP", "DISABLED", "DEFORMATION_FLOW")])


class OverrideCollection(list):
    def add(self):
        item = override("")
        self.append(item)
        return item

    def remove(self, index):
        self.pop(index)


def override(target_scp_id, parent_mode="KEEP", child_mode="KEEP", follow_mode="KEEP", strategy="KEEP"):
    return SimpleNamespace(target_scp_id=target_scp_id, parent_anchor_mode=parent_mode, child_anchor_mode=child_mode, follow_rotation_mode=follow_mode, rotation_strategy=strategy)


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))


if __name__ == "__main__":
    unittest.main()
