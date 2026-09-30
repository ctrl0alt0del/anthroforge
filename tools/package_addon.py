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
REQUIRED_NATIVE = ("af_fiber_ccd_v3_20.dll", "libomp.dll")


def tracked_package_files(source):
    raw = subprocess.check_output(["git", "-C", str(source), "ls-files", "-z"])
    names = [Path(x.decode()) for x in raw.split(b"\0") if x]
    return [p for p in names if p.as_posix() == "__init__.py" or
            (p.parts[0] in PACKAGE_DIRS and not p.as_posix().startswith("vendor/draft_skin/wheels/"))]


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
    if any(not path.is_file() for path in paths):
        raise ValueError("Package lacks required production Fiber CCD DLLs")
    return {path.name: {"size": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths}


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
