"""Verified, offline native dependency bundle; no runtime downloads."""
import hashlib
import json
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "vendor/quadwild"


def verify_bundle(root=ROOT):
    if platform.system() == 'Linux':
        from ..linux_dependencies import BUNDLE, verify
        return verify(BUNDLE / 'quadwild')
    if platform.system() != "Windows" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("QuadWild bundle requires Windows x64.")
    try:
        manifest = json.loads((root / "manifest.json").read_text())
        for name, digest in manifest["files"].items():
            path = (root / name).resolve()
            if not path.is_relative_to(root.resolve()): raise ValueError("Unsafe dependency path")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest: raise ValueError(name)
    except (OSError, ValueError, KeyError) as error:
        raise RuntimeError(f"QuadWild dependency bundle is missing or corrupt; reinstall the matching package: {error}") from error
    return root
