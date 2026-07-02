from pathlib import Path
import importlib.util
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _support import ensure_import_path, install_fake_modules

ensure_import_path()
install_fake_modules()


def _load_module():
    path = ADDON_ROOT / "core" / "vcp" / "dependent_loop_surface.py"
    _register_pkg("af_test_pkg", ADDON_ROOT)
    _register_pkg("af_test_pkg.core", ADDON_ROOT / "core")
    _register_pkg("af_test_pkg.core.vcp", ADDON_ROOT / "core" / "vcp")
    spec = importlib.util.spec_from_file_location("af_test_pkg.core.vcp.dependent_loop_surface", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _register_pkg(name, path):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules.setdefault(name, module)


dls = _load_module()


def _driver(*parent_ids):
    anchors = [SimpleNamespace(parent_id=value, attach_param="RAW") for value in parent_ids]
    return SimpleNamespace(loop_anchors=anchors)


class DependentLoopSurfaceTests(unittest.TestCase):
    def test_reference_surface_parent_id_requires_unique_parent(self):
        self.assertEqual(dls.reference_surface_parent_id(_driver("S1", "S1", "")), "S1")
        self.assertEqual(dls.reference_surface_parent_id(_driver("S1", "S2")), "")

    def test_surface_bias_clamps_to_driver_step(self):
        self.assertEqual(dls.surface_bias(0.0, 0.25), 0.0)
        self.assertEqual(dls.surface_bias(0.25, 0.25), 1.0)
        self.assertEqual(dls.surface_bias(-0.5, 0.25), 1.0)

    def test_fair_surface_loop_keeps_last_stable_pass(self):
        start = [{"bias": 1.0, "point": "A"}, {"bias": 1.0, "point": "B"}]
        good = [{"bias": 1.0, "point": "C"}, {"bias": 1.0, "point": "D"}]
        bad = [{"bias": 1.0, "point": "E"}, {"bias": 1.0, "point": "F"}]
        with patch.object(dls, "_fair_pass_total", return_value=3):
            with patch.object(dls, "_fair_world_pass", side_effect=[good, bad]):
                with patch.object(dls, "_stable_nodes", side_effect=[True, False]):
                    result = dls.fair_surface_loop(None, start, None, 1.0, None, None)
        self.assertEqual(result, good)
