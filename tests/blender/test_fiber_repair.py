from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

ADDON_ROOT = Path(__file__).resolve().parents[2]
if str(ADDON_ROOT.parent) not in sys.path: sys.path.insert(0, str(ADDON_ROOT.parent))

from anthroforge.core.vcp import fiber_pin_repair
from anthroforge.core.visualization import fiber_repair_runtime
from anthroforge.core.vcp.fiber_pin_repair_policy import (FiberPinCandidate, FiberPinRef,
                                                          FiberPinRepair, FiberPinRepairPlan,
                                                          FiberPinRepairReport)
from _helpers import BlenderTestCase


def _item(owner="SCP_A", raw="old"):
    return SimpleNamespace(parent_id=owner, attach_param=raw)


def _fiber():
    return SimpleNamespace(id="FIBER_1", a_parent_id="A", a_attach_param="a", b_parent_id="B",
                           b_attach_param="b", mid_touches=[_item()], loop_anchors=[_item()])


def _repair(role="TOUCH", index=1, owner="SCP_C"):
    pin = FiberPinRef("FIBER_1", role, index, "SCP_A", "old", (0, 0, 0), 0.0,
                      .002, "SCP_B", "UNRELATED")
    return FiberPinRepair(pin, FiberPinCandidate(owner, "new", (1, 2, 3), .001), "", False)


class FiberRepairTests(BlenderTestCase):
    def tearDown(self):
        fiber_repair_runtime._OPERATIONS.clear()
        super().tearDown()

    def test_endpoint_touch_and_loop_bindings_update_exact_fields(self):
        fiber = _fiber()
        for row in (_repair("ENDPOINT_A", 0, "EA"), _repair("ENDPOINT_B", 2, "EB"),
                    _repair("TOUCH", 1, "T"), _repair("LOOP", 0, "L")):
            fiber_pin_repair._set_pin(fiber, row)
        self.assertEqual((fiber.a_parent_id, fiber.b_parent_id), ("EA", "EB"))
        self.assertEqual((fiber.mid_touches[0].parent_id, fiber.loop_anchors[0].parent_id), ("T", "L"))

    def test_failed_validation_restores_complete_fiber_snapshot(self):
        fiber = _fiber(); root = SimpleNamespace(af_vcp_system=SimpleNamespace(fibers=[fiber]))
        plan = FiberPinRepairPlan(("sig",), (fiber.id,), (_repair(),), (), 1.0)
        graph = Mock()
        with patch.object(fiber_pin_repair, "fiber_pin_repair_signature", return_value=("sig",)), \
             patch.object(fiber_pin_repair, "_apply_and_validate", return_value=False), \
             patch.object(fiber_pin_repair, "_invalidate_preflight"), \
             patch.object(fiber_pin_repair, "_finish_repair_commit"):
            report = fiber_pin_repair.apply_fiber_pin_repair_plan(root, object(), plan, object(), graph)
        self.assertEqual((fiber.mid_touches[0].parent_id, report.failed_fibers), ("SCP_A", (fiber.id,)))

    def test_stale_plan_rejects_without_mutation(self):
        fiber = _fiber(); root = SimpleNamespace(af_vcp_system=SimpleNamespace(fibers=[fiber]))
        plan = FiberPinRepairPlan(("old",), (fiber.id,), (_repair(),), (), 1.0)
        with patch.object(fiber_pin_repair, "fiber_pin_repair_signature", return_value=("new",)):
            report = fiber_pin_repair.apply_fiber_pin_repair_plan(root, object(), plan, object(), Mock())
        self.assertEqual((fiber.mid_touches[0].parent_id, report.failed_fibers), ("SCP_A", ("STALE_PLAN",)))

    def test_no_invalid_pin_plan_still_recomputes_every_fiber(self):
        plan = FiberPinRepairPlan(("sig",), ("A", "B"), (), (), 1.0)
        session = SimpleNamespace(stale=lambda: False); root, scene = object(), object()
        operation = fiber_repair_runtime.FiberRepairOperation("token", "S", "R", 1, 2, session,
                                                               phase="READY", plan=plan)
        fiber_repair_runtime._OPERATIONS[(1, 2)] = operation
        report = FiberPinRepairReport(0, 0, 0, (), ())
        with patch.object(fiber_repair_runtime, "_operation_data", return_value=(root, scene)), \
             patch.object(fiber_repair_runtime, "register_fiber_sync", return_value=SimpleNamespace(_solver=object())), \
             patch.object(fiber_repair_runtime, "apply_fiber_pin_repair_plan", return_value=report), \
             patch.object(fiber_repair_runtime, "request_fiber_refinement_group", return_value="group") as request:
            self.assertTrue(fiber_repair_runtime.apply_fiber_repair("token", object()))
        request.assert_called_once_with(root, scene, ("A", "B"), "FINAL")

    def test_cancelled_recompute_cancels_its_group(self):
        session = SimpleNamespace(); operation = fiber_repair_runtime.FiberRepairOperation(
            "token", "S", "R", 1, 2, session, phase="RECOMPUTING", group_token="group")
        fiber_repair_runtime._OPERATIONS[(1, 2)] = operation
        with patch.object(fiber_repair_runtime, "cancel_fiber_refinement_group") as cancel:
            self.assertTrue(fiber_repair_runtime.cancel_fiber_repair("token"))
        cancel.assert_called_once_with("group")


if __name__ == "__main__":
    import unittest
    unittest.main(argv=[__file__])
