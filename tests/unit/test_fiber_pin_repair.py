import unittest

from core.vcp.fiber_pin_repair_policy import (FiberPinCandidate, FiberPinRef, FiberPinRepair,
                                              FiberPinRepairPlan, serialization_guard,
                                              use_owner_transfer)


def _pin(role="TOUCH", index=1, relation="UNRELATED", radius=.002):
    return FiberPinRef("FIBER_1", role, index, "SCP_A", "old", (0, 0, 0), 0.0,
                       radius, "SCP_B", relation)


def _candidate(owner="SCP_A", displacement=.001):
    return FiberPinCandidate(owner, "new", (1, 2, 3), displacement)


class FiberPinRepairTests(unittest.TestCase):
    def test_transfer_requires_every_strict_distance_rule(self):
        pin = _pin(); current = _candidate(displacement=.011); alternate = _candidate("SCP_B", .003)
        self.assertTrue(use_owner_transfer(pin, current, alternate))
        self.assertFalse(use_owner_transfer(pin, current, _candidate("SCP_B", .007)))
        self.assertFalse(use_owner_transfer(_pin(relation="ANCESTOR"), current, alternate))

    def test_serialization_guard_has_absolute_and_relative_floor(self):
        self.assertEqual(serialization_guard(.0001), 1.0e-6)
        self.assertEqual(serialization_guard(.1), 1.0e-4)

    def test_plan_exposes_only_risky_rows(self):
        safe = FiberPinRepair(_pin(), _candidate(), "", False)
        risky = FiberPinRepair(_pin("ENDPOINT_A", 0), _candidate(), "", True)
        plan = FiberPinRepairPlan((), (), (safe, risky), (), 1.0)
        self.assertEqual(plan.risky, (risky,))


if __name__ == "__main__":
    unittest.main()
