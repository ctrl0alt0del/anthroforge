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

from app.use_cases import attachment_toggle
from core.scp_runtime.attachment_gate import attachments_enabled


class AttachmentToggleTests(unittest.TestCase):
    def test_attachments_enabled_defaults_true(self):
        self.assertTrue(attachments_enabled(SimpleNamespace()))

    def test_handle_attachment_toggle_only_runs_enable_path(self):
        ctx = SimpleNamespace(scene=SimpleNamespace(af_attachments_enabled=False))
        with patch("app.use_cases.attachment_toggle._enable_attachments") as enable:
            self.assertIsNone(attachment_toggle.handle_attachment_toggle(ctx))
        enable.assert_not_called()

    def test_enable_attachments_recaptures_and_syncs(self):
        scene, root = SimpleNamespace(), object()
        with patch("app.use_cases.attachment_toggle._get_root", return_value=root), patch("app.use_cases.attachment_toggle._capture_authored", return_value=lambda *args: capture(*args)), patch("app.use_cases.attachment_toggle._empty_hints", return_value=lambda: {}), patch("app.use_cases.attachment_toggle._sync_scene", return_value=lambda **kwargs: sync(**kwargs)):
            capture, sync = Recorder(), Recorder()
            self.assertIsNone(attachment_toggle._enable_attachments(scene))
        self.assertEqual(capture.calls, [((root, scene), {})])
        self.assertEqual(sync.calls, [((), {"root": root, "scene": scene, "dirty_hints": {}, "source": "attachment_toggle", "event_type": "UPDATE"})])


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))


if __name__ == "__main__":
    unittest.main()
