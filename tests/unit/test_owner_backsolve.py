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

from core.shortcuts.owner_backsolve import owner_backsolve_enabled, owner_backsolve_is_custom, retrofit_owner_backsolve_defaults


class LegacyShortcut:
    owner_backsolve = False

    def is_property_set(self, key):
        return False if key == "owner_backsolve" else False


class MutableShortcut:
    def __init__(self, value=False, is_set=False):
        self._value = bool(value)
        self._is_set = bool(is_set)

    @property
    def owner_backsolve(self):
        return self._value

    @owner_backsolve.setter
    def owner_backsolve(self, value):
        self._value = bool(value)
        self._is_set = True

    def is_property_set(self, key):
        return self._is_set if key == "owner_backsolve" else False


class Root(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class OwnerBacksolveTests(unittest.TestCase):
    def test_legacy_unset_shortcut_stays_enabled(self):
        self.assertTrue(owner_backsolve_enabled(LegacyShortcut()))
        self.assertFalse(owner_backsolve_is_custom(LegacyShortcut()))

    def test_explicit_owner_backsolve_values_are_respected(self):
        self.assertFalse(owner_backsolve_enabled(SimpleNamespace(owner_backsolve=False)))
        self.assertTrue(owner_backsolve_enabled(SimpleNamespace(owner_backsolve=True)))
        self.assertFalse(owner_backsolve_is_custom(SimpleNamespace(owner_backsolve=False)))
        self.assertTrue(owner_backsolve_is_custom(SimpleNamespace(owner_backsolve=True)))

    def test_retrofit_owner_backsolve_defaults_sets_only_unset_rows(self):
        legacy, explicit = MutableShortcut(False, False), MutableShortcut(True, True)
        root = Root()
        root.af_shortcut_system = SimpleNamespace(shortcuts=[legacy, explicit])
        self.assertTrue(retrofit_owner_backsolve_defaults(root))
        self.assertFalse(retrofit_owner_backsolve_defaults(root))
        self.assertFalse(legacy.owner_backsolve)
        self.assertTrue(legacy.is_property_set("owner_backsolve"))
        self.assertTrue(explicit.owner_backsolve)
