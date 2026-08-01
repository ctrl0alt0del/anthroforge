import hashlib
import json
import platform
import sys
import tempfile
import zipfile
from pathlib import Path


ADDON_ROOT = Path(__file__).resolve().parents[2]
VENDOR_ROOT = ADDON_ROOT / "vendor" / "topology"
MANIFEST_PATH = VENDOR_ROOT / "manifest.json"


def ensure_worker_dependencies():
    _ensure_numeric_dependencies()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    _validate_runtime(manifest)
    target = Path(tempfile.gettempdir()) / "anthroforge_topology_vendor" / manifest["bundle"]
    if not (target / ".ready").exists():
        _extract(manifest, target)
    if str(target) not in sys.path:
        sys.path.insert(0, str(target))
    return target


def _ensure_numeric_dependencies():
    try:
        from ..draft_skin.vendor import ensure_worker_dependencies
    except ImportError:
        from adapters.draft_skin.vendor import ensure_worker_dependencies
    ensure_worker_dependencies()


def _validate_runtime(manifest):
    if tuple(sys.version_info[:2]) != tuple(manifest["python"]):
        raise RuntimeError("Topology generation requires Blender Python 3.11.")
    if platform.system() != "Windows" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("The topology worker bundle targets Windows x64.")
    for item in manifest["wheels"]:
        _verify(item)


def _verify(item):
    path = VENDOR_ROOT / "wheels" / item["file"]
    if not path.is_file():
        raise RuntimeError(f"Missing topology dependency: {path.name}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise RuntimeError(f"Topology dependency checksum failed: {path.name}")


def _extract(manifest, target):
    target.mkdir(parents=True, exist_ok=True)
    for item in manifest["wheels"]:
        with zipfile.ZipFile(VENDOR_ROOT / "wheels" / item["file"]) as archive:
            archive.extractall(target)
    (target / ".ready").write_text(manifest["bundle"], encoding="utf-8")
