import subprocess
import sys
import unittest
from dataclasses import replace
from importlib.util import find_spec

import numpy as np

from core.vcp.v3.manifest import V3_ACCEPTED_REFERENCE, V3_REJECTED_MODULES
from core.vcp.v3.policy import V3_PRODUCTION_POLICY, V3ShortcutMode, accepted_v3_request
from core.vcp.v3.production import V3_PRODUCTION_VERSION, begin_v3, solve_v3
from tests.unit.test_fiber_v2_planner import _anchors, _request


def _bent_request(cap=24):
    request = _request(_anchors(((0, 0, 0), (1, 1, 0), (2, 0, 0))), count=33)
    settings = replace(request.settings, max_accepted_steps=cap, curvature_weight=0.75)
    return replace(request, settings=settings)


class FiberV3ProductionTests(unittest.TestCase):
    def test_manifest_freezes_accepted_reference(self):
        self.assertEqual(V3_ACCEPTED_REFERENCE["name"], "REG_ADAPTIVE_SPACING")
        self.assertEqual(V3_ACCEPTED_REFERENCE["global_accepted_cap"], 180)

    def test_request_forces_accepted_objective(self):
        request = accepted_v3_request(_bent_request())
        self.assertEqual(request.settings.curvature_weight, 0.0)
        self.assertAlmostEqual(request.settings.fidelity_weight, 0.01)

    def test_v3_is_deterministic_at_fixed_cap(self):
        request = _bent_request(20)
        first, second = solve_v3(request), solve_v3(request)
        self.assertEqual(first.result.points, second.result.points)
        self.assertEqual(first.result.termination, second.result.termination)

    def test_result_reports_v3_identity_and_zero_curvature(self):
        package = solve_v3(_bent_request(8), use_planner=False)
        self.assertEqual(package.result.engine_version, V3_PRODUCTION_VERSION)
        self.assertEqual(package.result.diagnostics.effective_curvature_weight, 0.0)

    def test_checkpoint_continues_to_terminal_result(self):
        session = begin_v3(_bent_request(12), checkpoint_steps=2, use_planner=False)
        while not session.done and not session.checkpoint_ready: session.step()
        while not session.done: session.step()
        self.assertTrue(session.package.result.validated)
        self.assertLessEqual(session.package.result.diagnostics.accepted_steps, 12)

    def test_shadow_and_off_have_identical_solver_output(self):
        request = _bent_request(12)
        off_policy = replace(V3_PRODUCTION_POLICY, shortcut_mode=V3ShortcutMode.OFF)
        shadow_policy = replace(V3_PRODUCTION_POLICY, shortcut_mode=V3ShortcutMode.SHADOW)
        off = solve_v3(request, policy=off_policy)
        shadow = solve_v3(request, policy=shadow_policy)
        self.assertTrue(np.array_equal(off.result.points, shadow.result.points))
        self.assertEqual(off.result.termination, shadow.result.termination)

    def test_production_import_excludes_rejected_modules(self):
        output = subprocess.check_output([sys.executable, "-c", _import_probe()], text=True)
        self.assertEqual(output.strip(), "")

    def test_rejected_solver_modules_were_removed(self):
        for name in V3_REJECTED_MODULES:
            self.assertIsNone(find_spec(_rejected_import(name)), name)


def _import_probe():
    rejected = repr(tuple(V3_REJECTED_MODULES))
    return ("import sys; import core.vcp.v3.production; "
            f"r={rejected}; print('\\n'.join(n for n in sys.modules if any(n.endswith(x) for x in r)))")


def _rejected_import(name):
    prefix = "core.vcp." if name.startswith("v3_") else "core.vcp.v2."
    return prefix + name


if __name__ == "__main__":
    unittest.main()
