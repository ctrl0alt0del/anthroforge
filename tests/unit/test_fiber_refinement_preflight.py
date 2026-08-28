from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import DEFAULT, patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _support import ensure_import_path, install_fake_modules

ensure_import_path()
install_fake_modules()

from core.visualization import fiber_refinement as refinement
from core.vcp.fiber_anchor_preflight import FiberAnchorPreflightResult


def invalid_result():
    violation = SimpleNamespace(role="TOUCH", authored_index=1)
    return FiberAnchorPreflightResult(False, (violation,), ("key",), 2, 1)


class FiberRefinementPreflightTests(unittest.TestCase):
    def setUp(self):
        refinement._JOBS.clear()
        refinement._QUEUE.clear()

    def test_invalid_preflight_stops_before_session_job_timer_or_event(self):
        root = SimpleNamespace(name="Root")
        scene, fiber = SimpleNamespace(), SimpleNamespace(id="F1")
        with patch.object(refinement, "_hard_anchor_preflight", return_value=invalid_result()), \
             patch.object(refinement, "_prepared_session", side_effect=AssertionError("session started")) as prepare, \
             patch.multiple(refinement, rollback_engine_migration=DEFAULT, mark_fiber_output_stale=DEFAULT,
                            set_fiber_invalid_reason=DEFAULT, set_fiber_recompute_status=DEFAULT,
                            set_fiber_not_converged=DEFAULT) as mocks:
            result = refinement.request_fiber_refinement(root, scene, fiber, show_preview=True)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "Fiber has 1 invalid hard anchor; planning cannot start.")
        prepare.assert_not_called()
        mocks["mark_fiber_output_stale"].assert_called_once_with(scene, "Root", "F1")

    def test_corrected_preflight_permits_engine_session_and_launch(self):
        root = SimpleNamespace(name="Root")
        scene, fiber = SimpleNamespace(), SimpleNamespace(id="F1")
        valid = FiberAnchorPreflightResult(True, (), ("key",), 0, 0)
        session = SimpleNamespace(invalid_reason="")
        expected = refinement.RefinementRequest(True)
        with patch.object(refinement, "_hard_anchor_preflight", return_value=valid), \
             patch.object(refinement, "_prepared_session", return_value=session) as prepare, \
             patch.object(refinement, "_launch_refinement", return_value=expected) as launch:
            actual = refinement.request_fiber_refinement(root, scene, fiber)
        self.assertIs(actual, expected)
        prepare.assert_called_once_with(root, scene, fiber, "FINAL")
        launch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
