"""Release packages contain the current numerical libraries, not historical builds."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


def package_tool():
    folder = Path(__file__).resolve().parents[2] / 'tools'
    spec = importlib.util.spec_from_file_location('package_addon', folder / 'package_addon.py')
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, 'path', [str(folder), *sys.path]): spec.loader.exec_module(module)
    return module


class PackageInventoryTests(unittest.TestCase):
    def test_current_libraries_and_sources_survive_filtering(self):
        tool = package_tool()
        for name in tool.REQUIRED_NATIVE:
            self.assertTrue(tool.production_file(Path('native/fiber_ccd') / name))
        for name in ('native/smoothing/af_height_smoothing_v1.dll', 'native/smoothing/vendor/PIQP-LICENSE',
                     'core/muscle_pairs/coordinator.py', 'native/fiber_ccd/layer_stacking/api.hpp'):
            self.assertTrue(tool.production_file(Path(name)))

    def test_historical_binaries_and_wheels_are_not_distributed(self):
        tool = package_tool()
        for name in ('native/fiber_ccd/af_fiber_ccd_v3_20.dll', 'native/fiber_ccd/experiment.dll',
                     'vendor/draft_skin/wheels/unused.whl', 'tests/unit/test_example.py'):
            self.assertFalse(tool.production_file(Path(name)))
