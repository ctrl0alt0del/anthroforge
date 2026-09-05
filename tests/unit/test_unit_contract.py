from pathlib import Path
import sys
import unittest

ADDON_ROOT = Path(__file__).resolve().parents[2]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from core.units import (
    METERS_PER_WORLD_UNIT_KEY,
    UNIT_STATE_DECLARED,
    UNIT_STATE_KEY,
    UNIT_STATE_UNDECLARED,
    UNIT_VERSION_KEY,
    contract_from_payload,
    declare_unit_contract,
    physical_scale_label,
    resolve_unit_contract,
    unit_contract_payload,
    world_distance_in_meters,
)


class RootUnitContractTests(unittest.TestCase):
    def test_absent_metadata_is_undeclared_without_mutation(self):
        root = {}
        contract = resolve_unit_contract(root)
        self.assertEqual((contract.state, contract.version, contract.meters_per_world_unit),
                         (UNIT_STATE_UNDECLARED, 0, None))
        self.assertEqual(root, {})

    def test_declaration_round_trips_payload_and_physical_distance(self):
        root = {}
        declare_unit_contract(root, 0.01)
        payload = unit_contract_payload(root)
        self.assertEqual(contract_from_payload(payload), resolve_unit_contract(root))
        self.assertAlmostEqual(world_distance_in_meters(root, 25.0), 0.25)
        self.assertEqual(physical_scale_label(root), "1 world unit = 0.01 m")

    def test_declared_keys_are_versioned_and_additive(self):
        root = {"keep": 7}
        declare_unit_contract(root, 1.0)
        self.assertEqual((root[UNIT_STATE_KEY], root[UNIT_VERSION_KEY],
                          root[METERS_PER_WORLD_UNIT_KEY], root["keep"]),
                         (UNIT_STATE_DECLARED, 1, 1.0, 7))

    def test_invalid_or_missing_payload_is_undeclared(self):
        invalid = {"state": UNIT_STATE_DECLARED, "version": 1,
                   "meters_per_world_unit": float("nan")}
        future = {"state": UNIT_STATE_DECLARED, "version": 2,
                  "meters_per_world_unit": 1.0}
        self.assertEqual(contract_from_payload(None).state, UNIT_STATE_UNDECLARED)
        self.assertEqual(contract_from_payload(invalid).state, UNIT_STATE_UNDECLARED)
        self.assertEqual(contract_from_payload(future).state, UNIT_STATE_UNDECLARED)
