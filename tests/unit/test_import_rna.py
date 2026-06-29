from pathlib import Path
import importlib.util
import sys
import unittest

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)


def _load_rna():
    path = ADDON_ROOT / "core" / "importing" / "rna.py"
    spec = importlib.util.spec_from_file_location("import_rna_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


apply_scalar_dict = _load_rna().apply_scalar_dict


class _Bag:
    keep = 1


class ImportRnaTests(unittest.TestCase):
    def test_apply_scalar_dict_ignores_unknown_keys(self):
        item = _Bag()
        apply_scalar_dict(item, {"keep": 2, "collision_margin": 0.2, "damping": 0.3})
        self.assertEqual(item.keep, 2)
        self.assertFalse(hasattr(item, "collision_margin"))
