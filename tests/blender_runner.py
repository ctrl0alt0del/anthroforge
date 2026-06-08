from pathlib import Path
import os
import sys
import unittest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _support import ensure_import_path

ensure_import_path()
os.environ["AF_DEPS_TRACE"] = "0"

suite = unittest.defaultTestLoader.discover("tests/blender")
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
