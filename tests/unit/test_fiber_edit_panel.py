import importlib
from pathlib import Path
import sys
import types
import unittest
from types import SimpleNamespace

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from _support import install_fake_modules

bpy = install_fake_modules()
bpy.types = getattr(bpy, "types", SimpleNamespace())
bpy.types.Panel = getattr(bpy.types, "Panel", object)
PACKAGE = types.ModuleType("_af6_panel_package")
PACKAGE.__path__ = [str(ADDON_ROOT)]
sys.modules.setdefault(PACKAGE.__name__, PACKAGE)
Panel = importlib.import_module(f"{PACKAGE.__name__}.ui.panels.fiber_edit_panel").AF_PT_FiberEditPanel


class Layout:
    def __init__(self):
        self.labels = []

    def box(self):
        return self

    def label(self, text="", **_kwargs):
        self.labels.append(text)


class FiberEditPanelTests(unittest.TestCase):
    def test_deep_containment_is_presented_without_unsigned_clearance(self):
        violation = SimpleNamespace(role=SimpleNamespace(value="TOUCH"), authored_index=4,
                                    owner_id="SCP_10", relation="ANCESTOR", blocker_id="SCP_4",
                                    contained=True, measured_clearance=2.0,
                                    configured_clearance=.002, action="Re-author.")
        layout = Layout()
        Panel()._draw_anchor_violation(layout, violation)
        self.assertIn("Inside blocker: containment invalidates this anchor.", layout.labels)
        self.assertFalse(any(text.startswith("Clearance") for text in layout.labels))


if __name__ == "__main__":
    unittest.main()
