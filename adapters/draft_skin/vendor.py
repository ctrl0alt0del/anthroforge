import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


ADDON_ROOT = Path(__file__).resolve().parents[2]
VENDOR_ROOT = ADDON_ROOT / "vendor" / "draft_skin"
MANIFEST_PATH = VENDOR_ROOT / "manifest.json"


def ensure_worker_dependencies():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    _validate_runtime(manifest)
    target = Path(tempfile.gettempdir()) / "anthroforge_skin_vendor" / manifest["bundle"]
    if not (target / ".ready").exists():
        _extract_bundle(manifest, target)
    if str(target) not in sys.path:
        sys.path.insert(0, str(target))
    return target


def _validate_runtime(manifest):
    if tuple(sys.version_info[:2]) != tuple(manifest["python"]):
        raise RuntimeError("Draft skin requires Blender Python 3.11.")
    if platform.system() != "Windows" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("This draft skin worker bundle targets Windows x64.")
    for item in manifest["wheels"]:
        _verify_wheel(item)


def _verify_wheel(item):
    path = VENDOR_ROOT / "wheels" / item["file"]
    if not path.is_file():
        raise RuntimeError(f"Missing draft skin dependency: {path.name}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != item["sha256"]:
        raise RuntimeError(f"Draft skin dependency checksum failed: {path.name}")


def _extract_bundle(manifest, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{manifest['bundle']}-", dir=target.parent))
    try:
        for item in manifest["wheels"]:
            _extract_wheel(item, temporary)
        (temporary / ".ready").write_text(manifest["bundle"], encoding="utf-8")
        _install_temporary(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def _extract_wheel(item, target):
    path = VENDOR_ROOT / "wheels" / item["file"]
    with zipfile.ZipFile(path) as archive:
        archive.extractall(target)


def _install_temporary(temporary, target):
    try:
        os.replace(temporary, target)
    except OSError:
        if not (target / ".ready").exists():
            raise
