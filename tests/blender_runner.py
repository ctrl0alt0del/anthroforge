from pathlib import Path
import importlib.util
import os
import sys
import unittest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
BLENDER_TESTS = HERE / "blender"
if str(BLENDER_TESTS) not in sys.path:
    sys.path.insert(0, str(BLENDER_TESTS))

from _support import ensure_import_path

ensure_import_path()


def _load_worktree_addon():
    path = HERE.parent / "__init__.py"
    existing = sys.modules.get("anthroforge")
    if existing is not None:
        assert Path(existing.__file__).resolve() == path.resolve(), "Wrong AnthroForge checkout loaded"
        return
    spec = importlib.util.spec_from_file_location("anthroforge", path,
                                                submodule_search_locations=[str(HERE.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["anthroforge"] = module
    spec.loader.exec_module(module)


_load_worktree_addon()
os.environ["AF_DEPS_TRACE"] = "0"
os.environ.setdefault("AF_FIBER_ENGINE", "V1")

pattern = next((arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--pattern=")), "test*.py")
test_name = next((arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--test=")), "")
suite = (unittest.defaultTestLoader.loadTestsFromName(test_name) if test_name else
         unittest.defaultTestLoader.discover("tests/blender", pattern=pattern))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
