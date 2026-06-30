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

from core.selection_order import ordered_selected_objects, selection_order, update_selection_order


class FakeSelectable:
    def __init__(self, name):
        self.name = name
        self._selected = False

    def select_get(self):
        return bool(self._selected)

    def select_set(self, value):
        self._selected = bool(value)


def scene(*objects):
    return SimpleNamespace(objects=list(objects), af_selection_order_json="[]")


class SelectionOrderTests(unittest.TestCase):
    def test_update_selection_order_tracks_active_append(self):
        a, b = FakeSelectable("A"), FakeSelectable("B")
        scn = scene(a, b)
        a.select_set(True)
        self.assertEqual(update_selection_order(scn, [a], a), ["A"])
        b.select_set(True)
        self.assertEqual(update_selection_order(scn, [a, b], b), ["A", "B"])

    def test_update_selection_order_prunes_removed_items(self):
        a, b, c = FakeSelectable("A"), FakeSelectable("B"), FakeSelectable("C")
        scn = scene(a, b, c)
        scn.af_selection_order_json = '["A","B","C"]'
        a.select_set(True)
        c.select_set(True)
        self.assertEqual(update_selection_order(scn, [a, c], a), ["A", "C"])

    def test_ordered_selected_objects_preserves_stored_order(self):
        a, b, c = FakeSelectable("A"), FakeSelectable("B"), FakeSelectable("C")
        scn = scene(a, b, c)
        scn.af_selection_order_json = '["B","A","C"]'
        for obj in (a, b, c):
            obj.select_set(True)
        ordered = ordered_selected_objects(scn, [c, a, b], c)
        self.assertEqual([obj.name for obj in ordered], ["B", "A", "C"])
        self.assertEqual(selection_order(scn), ["B", "A", "C"])


if __name__ == "__main__":
    unittest.main()
