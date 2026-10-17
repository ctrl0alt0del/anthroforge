"""Shared platform selection for maintained native libraries and workers."""
import platform
import sys
from pathlib import Path


def library_path(relative):
    path = Path(__file__).resolve().parents[1] / relative
    if platform.system() == 'Linux':
        return path.with_name('lib' + path.stem + '.so')
    return path


def python_executable():
    name = 'python.exe' if platform.system() == 'Windows' else 'python3.11'
    candidate = Path(sys.prefix) / 'bin' / name
    if candidate.is_file():
        return candidate
    if 'bpy' not in sys.modules:
        return Path(sys.executable)
    raise RuntimeError('Matching Blender Python executable is missing: ' + str(candidate))


def executable_name(name):
    return name + ('.exe' if platform.system() == 'Windows' else '')
