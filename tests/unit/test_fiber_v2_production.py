import subprocess
import sys
import unittest

from core.vcp.v2.production import V2_ACCEPTED_FEATURES, V2_PRODUCTION_VERSION


class FiberV2ProductionFacadeTests(unittest.TestCase):
    def test_manifest_is_immutable_and_versioned(self):
        self.assertIsInstance(V2_ACCEPTED_FEATURES, tuple)
        self.assertEqual(V2_PRODUCTION_VERSION, "fiber-v2-production-2")

    def test_production_import_excludes_rejected_solvers(self):
        code = _production_import_probe()
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


def _production_import_probe():
    names = ("solver_v25_branch2", "solver_p71", "solver_p72", "solver_p8", "solver_p81", "solver_p82")
    check = ",".join(repr(f"core.vcp.v2.{name}") for name in names)
    return ("import sys; import core.vcp.v2.production; "
            f"raise SystemExit(any(name in sys.modules for name in ({check},)))")
