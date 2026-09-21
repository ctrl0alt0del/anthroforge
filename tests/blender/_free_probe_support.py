"""Exact-checkout loader for disposable AF-24 GUI and measurement probes."""
from pathlib import Path
import importlib.util
import os
import sys

ADDON_PATH = Path(__file__).resolve().parents[2]


def load():
    for path in (ADDON_PATH, ADDON_PATH / 'tests', ADDON_PATH / 'tests' / 'blender'):
        if str(path) not in sys.path: sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location('anthroforge', ADDON_PATH / '__init__.py', submodule_search_locations=[str(ADDON_PATH)])
    module = importlib.util.module_from_spec(spec); sys.modules['anthroforge'] = module; spec.loader.exec_module(module)
    os.environ['AF_DEPS_TRACE'] = '0'; os.environ['AF_FIBER_ENGINE'] = 'V1'
    return module


def output_directory():
    directory = next((v.split('=', 1)[1] for v in sys.argv if v.startswith('--output=')), None)
    if directory is None: raise ValueError('Supply an explicit --output= artifact directory.')
    path = Path(directory); path.mkdir(parents=True, exist_ok=True)
    return path
