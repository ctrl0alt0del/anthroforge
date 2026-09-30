"""Read-only validation and import of packaged Draft Skin dependencies."""

import hashlib
import json
import platform
import sys
from pathlib import Path, PurePosixPath


ADDON_ROOT = Path(__file__).resolve().parents[2]
VENDOR_ROOT = ADDON_ROOT / "vendor" / "draft_skin"
MANIFEST_PATH = VENDOR_ROOT / "manifest.json"
PACKAGE_ROOTS = ("scipy", "skimage", "PIL", "imageio", "networkx",
                 "lazy_loader", "packaging", "tifffile")
REPAIR = "Reinstall the matching AnthroForge Windows x64 / Blender 5.0.1 package."


def _failure(reason):
    raise RuntimeError(f"Draft Skin dependencies: {reason}. {REPAIR}")


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _manifest():
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        _failure(f"missing or invalid source manifest ({error})")


def _runtime(source, payload):
    if payload.get("schema") != 1 or payload.get("bundle") != source.get("bundle"):
        _failure("incompatible bundle schema or version")
    if payload.get("platform") != "win64" or platform.system() != "Windows":
        _failure("Windows x64 bundle required")
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        _failure("Windows x64 host required")
    if payload.get("python") != [3, 11] or tuple(sys.version_info[:2]) != (3, 11):
        _failure("CPython 3.11 required")
    _host_versions(payload)


def _host_versions(payload):
    bpy = sys.modules.get("bpy")
    if bpy is None or list(bpy.app.version) != payload.get("blender"):
        _failure("Blender host version differs from bundle")
    import numpy
    if numpy.__version__ != payload.get("numpy"):
        _failure("Blender NumPy version differs from bundle")


def _bundle_path(source):
    name = source.get("bundle")
    if name != "win64-cp311-v2":
        _failure("unsupported source bundle version")
    path = VENDOR_ROOT / "bundles" / name
    if not path.is_dir() or path.is_symlink():
        _failure("packaged bundle is missing or linked")
    return path


def _payload(source, path):
    manifest = path / "bundle.json"
    try:
        data = manifest.read_bytes()
        if _digest(data) != source.get("bundle_lock_sha256"):
            _failure("bundle manifest checksum failed")
        return json.loads(data)
    except (OSError, ValueError) as error:
        _failure(f"bundle manifest missing or invalid ({error})")


def _expected_files(payload):
    items = payload.get("files")
    if not isinstance(items, list) or not items:
        _failure("bundle file inventory missing")
    paths = [item.get("path") for item in items if isinstance(item, dict)]
    if len(paths) != len(items) or any(not isinstance(p, str) for p in paths):
        _failure("bundle file inventory invalid")
    if len({p.casefold() for p in paths}) != len(paths):
        _failure("duplicate bundle paths")
    return items


def _validate_name(name):
    if not name or name.startswith("/") or "\\" in name or ":" in name:
        _failure(f"unsafe bundle path {name}")
    if any(part in {"", ".", ".."} for part in name.split("/")):
        _failure(f"unsafe bundle path {name}")
    if PurePosixPath(name).as_posix() != name:
        _failure(f"unsafe bundle path {name}")


def _io_root(path):
    if platform.system() != "Windows":
        return path
    absolute = str(Path(path).absolute())
    if absolute.startswith("\\\\?\\"):
        return Path(absolute)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


def _actual_files(path):
    actual = set()
    root = _io_root(path)
    for member in root.rglob("*"):
        if member.is_symlink():
            _failure(f"linked bundle path {member.name}")
        if member.is_file():
            actual.add(member.relative_to(root).as_posix())
        elif not member.is_dir():
            _failure(f"invalid bundle path {member.name}")
    return actual


def _verify_files(path, payload):
    items = _expected_files(payload)
    expected = {item["path"] for item in items} | {"bundle.json"}
    for name in expected:
        _validate_name(name)
    if _actual_files(path) != expected:
        _failure("bundle has missing or unexpected files")
    for item in items:
        member = _io_root(path).joinpath(*PurePosixPath(item["path"]).parts)
        if member.stat().st_size != item.get("size") or _digest(member.read_bytes()) != item.get("sha256"):
            _failure(f"bundle file checksum failed: {item['path']}")


def _preloaded(path):
    base = _io_root(path.resolve())
    for root in PACKAGE_ROOTS:
        module = sys.modules.get(root)
        origin = getattr(module, "__file__", None)
        if module is not None and (not origin or not _io_root(Path(origin).resolve()).is_relative_to(base)):
            _failure(f"conflicting preloaded package: {root}")


def ensure_worker_dependencies():
    source = _manifest()
    path = _bundle_path(source)
    payload = _payload(source, path)
    _runtime(source, payload)
    if payload.get("wheels") != source.get("wheels"):
        _failure("bundle wheel provenance differs")
    _verify_files(path, payload)
    _preloaded(path)
    sys.dont_write_bytecode = True
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    return path
