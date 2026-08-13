from pathlib import Path
import sys

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, empty_object, root
from anthroforge.core.importing.extract import root_snapshot
from anthroforge.core.units import (
    METERS_PER_WORLD_UNIT_KEY,
    UNIT_STATE_DECLARED,
    UNIT_STATE_KEY,
    UNIT_VERSION_KEY,
    resolve_unit_contract,
)
from anthroforge.core.utils import ensure_af_root


class RootUnitContractBlenderTests(BlenderTestCase):
    def test_new_root_declares_si_and_exports_contract(self):
        root_obj = root()
        snapshot = root_snapshot(root_obj)
        self.assertEqual((root_obj[UNIT_STATE_KEY], root_obj[UNIT_VERSION_KEY],
                          root_obj[METERS_PER_WORLD_UNIT_KEY]),
                         (UNIT_STATE_DECLARED, 1, 1.0))
        self.assertEqual(snapshot.unit_contract["meters_per_world_unit"], 1.0)

    def test_existing_legacy_root_stays_undeclared_and_unmodified(self):
        legacy = empty_object("LegacyRoot")
        legacy["anthroforge_root"] = True
        before = set(legacy.keys())
        self.assertIs(ensure_af_root(bpy.context.scene), legacy)
        self.assertEqual(resolve_unit_contract(legacy).state, "UNDECLARED")
        self.assertEqual((set(legacy.keys()), root_snapshot(legacy).unit_contract), (before, None))
