"""Offline verification of the Linux development bundle prepared at installation."""
import hashlib
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / 'vendor/linux'


def verify(folder):
    manifest = json.loads((folder / 'inventory.json').read_text())
    verify_lock(manifest)
    expected = manifest['files']
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob('*')
              if p.is_file() and '__pycache__' not in p.parts and p.name != 'inventory.json'}
    if actual != set(expected):
        raise RuntimeError('Linux dependency inventory mismatch; rerun tools/cloud/geometry_setup.py')
    for name, digest in expected.items():
        path = folder / name
        if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
            raise RuntimeError('Unsafe Linux dependency path: ' + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Linux dependency checksum mismatch: ' + name)
    return folder


def ensure():
    if platform.system() != 'Linux' or platform.machine().lower() != 'x86_64':
        raise RuntimeError('Linux x64 dependency bundle required')
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError('Linux geometry bundle requires CPython 3.11')
    folder = verify(BUNDLE / 'packages')
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    sys.dont_write_bytecode = True
    return folder


def verify_lock(manifest):
    lock = hashlib.sha256((ROOT / "tools/cloud/linux-wheels.json").read_bytes()).hexdigest()
    if manifest.get("wheel_lock") != lock:
        raise RuntimeError("Linux dependency lock changed; reinstall the development bundle")
