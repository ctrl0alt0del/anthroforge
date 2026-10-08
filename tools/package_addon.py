"""Create an offline AnthroForge ZIP with pre-expanded Draft Skin dependencies."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from build_draft_skin_vendor import ROOT, VENDOR, build_bundle


PACKAGE_DIRS = {"adapters", "app", "core", "native", "operators",
                "properties", "ui", "vendor", "workers"}
REQUIRED_NATIVE = ("af_fiber_ccd_v3_32.dll", "libomp.dll")


def tracked_package_files(source):
    raw = subprocess.check_output(["git", "-C", str(source), "ls-files", "-z"])
    names = [Path(x.decode()) for x in raw.split(b"\0") if x]
    return [p for p in names if production_file(p)]


def production_file(path):
    if path.parts[:2] == ('native', 'fiber_ccd') and path.suffix == '.dll':
        return path.name in REQUIRED_NATIVE
    return path.as_posix() == '__init__.py' or (path.parts[0] in PACKAGE_DIRS and
        not path.as_posix().startswith('vendor/draft_skin/wheels/'))


def stage_files(source, target):
    for relative in tracked_package_files(source):
        path = source / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Invalid package source: {relative}")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def native_inventory(stage):
    paths = [stage / "native" / "fiber_ccd" / name for name in REQUIRED_NATIVE]
    paths.append(stage / 'native/smoothing/af_height_smoothing_v1.dll')
    if any(not path.is_file() for path in paths):
        raise ValueError("Package lacks required production native DLLs")
    verify_pair_abi(stage)
    verify_auxiliary_abi(stage)
    return {path.name: {"size": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths}


def verify_pair_abi(stage):
    import sys
    directory = stage / 'native/fiber_ccd'
    script = ('import ctypes, os, sys\n'
        'with os.add_dll_directory(sys.argv[1]):\n'
        ' library = ctypes.CDLL(sys.argv[2])\n'
        ' assert library.af_pair_version() == 1 and library.af_pair_storage_version() == 1, "Missing muscle_pair_detection.v1 storage"\n'
        ' assert library.af_layer_order_version() == 1, "Missing muscle_layer_order.v1"\n'
        ' assert library.af_stacking_version() == 1, "Missing muscle_stacking.v1"\n'
        ' assert library.af_vector_stacking_version() == 1, "Missing muscle_vector_stacking.v1"\n'
        ' assert library.af_relationship_policy_version() == 1, "Missing muscle_relationships.v1"\n'
        ' assert library.af_explicit_order_version() == 1 and library.af_stack_constraint_capture_version() == 1, "Missing muscle_explicit_order.v1"\n'
        ' for name in ("af_vector_stack_submit_v1", "af_vector_stack_metrics", "af_stack_legacy_diagnostic", "af_relationship_effective_summary", "af_layer_storage_stats"): getattr(library, name)\n'
        ' for name in sys.argv[3:]: getattr(library, "af_pair_" + name)\n')
    subprocess.run([sys.executable, '-c', script, str(directory), str(directory / REQUIRED_NATIVE[0]),
        'create', 'destroy', 'submit', 'poll', 'cancel', 'release', 'summary', 'footprint', 'build_field', 'limiting', 'blend_directions', 'orientation', 'storage_stats'], check=True)


def verify_auxiliary_abi(stage):
    import sys
    fiber = stage / 'native/fiber_ccd' / REQUIRED_NATIVE[0]
    height = stage / 'native/smoothing/af_height_smoothing_v1.dll'
    script = ('import ctypes, os, sys\n'
        'with os.add_dll_directory(os.path.dirname(sys.argv[1])):\n'
        ' fiber = ctypes.CDLL(sys.argv[1]); height = ctypes.CDLL(sys.argv[2])\n'
        ' assert fiber.af_warning_async_version() == 1, "Missing warning worker ABI"\n'
        ' assert height.af_height_version() == 1, "Missing height smoothing ABI"\n'
        ' getattr(height, "af_height_smooth")\n')
    subprocess.run([sys.executable, '-c', script, str(fiber), str(height)], check=True)


def add_file(archive, path, name):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    with path.open("rb") as source, archive.open(info, "w") as target:
        shutil.copyfileobj(source, target)


def make_zip(stage, output):
    with zipfile.ZipFile(output, "w", allowZip64=True, compresslevel=6) as archive:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                add_file(archive, path, path.relative_to(stage.parent).as_posix())


def package(source, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="af10-package-", dir=output.parent) as temporary:
        stage = Path(temporary) / "anthroforge"
        stage.mkdir()
        stage_files(source, stage)
        native = native_inventory(stage)
        manifest = json.loads((source / VENDOR / "manifest.json").read_text())
        lock = build_bundle(source, stage / VENDOR / "bundles" / manifest["bundle"])
        make_zip(stage, output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    report = {"zip": str(output), "sha256": digest, "bundle": manifest["bundle"],
              "bundle_lock_sha256": lock, "source": str(source), "native": native}
    output.with_suffix(output.suffix + ".json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "anthroforge-win64-cp311.zip")
    args = parser.parse_args()
    print(json.dumps(package(args.source.resolve(), args.output.resolve()), indent=2))


if __name__ == "__main__":
    main()
