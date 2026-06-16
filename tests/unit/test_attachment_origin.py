from pathlib import Path
import sys
import unittest
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _support import ensure_import_path, install_fake_modules

ensure_import_path()
install_fake_modules()

from app.use_cases.attachment_origin import move_active_origin_to_attachment


class AttachmentOriginTests(unittest.TestCase):
    def test_move_active_origin_requires_object_mode(self):
        ctx = type("Ctx", (), {"mode": "EDIT_MESH"})()
        result = move_active_origin_to_attachment(ctx)
        self.assertEqual((result.ok, result.message), (False, "Switch to Object Mode first."))

    def test_move_active_origin_reports_success(self):
        ctx = type("Ctx", (), {"mode": "OBJECT"})()
        pair = (object(), object())
        with patch("app.use_cases.attachment_origin.root_for_context", return_value=object()):
            with patch("app.use_cases.attachment_origin._resolved_active_child", return_value=(pair, "")):
                with patch("app.use_cases.attachment_origin._move_origin_for_child", return_value=(True, "")):
                    result = move_active_origin_to_attachment(ctx)
        self.assertEqual((result.ok, result.message), (True, "Moved SCP origin to attachment."))


if __name__ == "__main__":
    unittest.main()
