"""Build the pinned Draft Skin binary bundle before distributing the add-on."""

import argparse
import base64
import csv
import hashlib
import io
import json
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
VENDOR = Path("vendor/draft_skin")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded_digest(data):
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def safe_name(name):
    path = PurePosixPath(name)
    if not name or "\\" in name or ":" in name or name.startswith("/"):
        raise ValueError(f"Unsafe wheel path: {name}")
    if any(part in {"", ".", ".."} for part in name.split("/")):
        raise ValueError(f"Unsafe wheel path: {name}")
    if path.as_posix() != name:
        raise ValueError(f"Unsafe wheel path: {name}")
    return path


def wheel_members(archive):
    members = [item for item in archive.infolist() if not item.is_dir()]
    names = [item.filename for item in members]
    for name in names:
        safe_name(name)
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("Duplicate wheel path")
    if any(stat.S_ISLNK(item.external_attr >> 16) for item in members):
        raise ValueError("Wheel contains a symbolic link")
    if any(".data/" in name for name in names):
        raise ValueError("Unsupported wheel .data layout")
    return members


def wheel_metadata(archive, members, filename):
    names = [m.filename for m in members]
    wheels = [name for name in names if name.endswith(".dist-info/WHEEL")]
    if len(wheels) != 1 or not any(name.endswith(".dist-info/METADATA") for name in names):
        raise ValueError("Wheel metadata missing")
    metadata = archive.read(wheels[0]).decode("utf-8")
    tag = "-".join(filename.removesuffix(".whl").split("-")[-3:])
    if "Wheel-Version: 1.0" not in metadata or f"Tag: {tag}" not in metadata:
        raise ValueError(f"Unsupported WHEEL metadata or tag: {filename}")


def wheel_record(archive, members):
    records = [m.filename for m in members if m.filename.endswith(".dist-info/RECORD")]
    if len(records) != 1:
        raise ValueError("Wheel must contain one RECORD")
    rows = list(csv.reader(io.StringIO(archive.read(records[0]).decode("utf-8"))))
    if len({row[0].casefold() for row in rows}) != len(rows):
        raise ValueError("Duplicate RECORD path")
    if {row[0] for row in rows} != {m.filename for m in members}:
        raise ValueError("Wheel files and RECORD differ")
    return {row[0]: row for row in rows}


def verify_record(name, data, row):
    if name.endswith(".dist-info/RECORD"):
        return
    if len(row) != 3 or row[1] != "sha256=" + encoded_digest(data):
        raise ValueError(f"Wheel RECORD hash mismatch: {name}")
    if row[2] != str(len(data)):
        raise ValueError(f"Wheel RECORD size mismatch: {name}")


def verify_wheel_source(source, item):
    path = source / VENDOR / "wheels" / item["file"]
    if not path.is_file() or digest(path.read_bytes()) != item["sha256"]:
        raise ValueError(f"Wheel missing or SHA mismatch: {item['file']}")
    name = item["file"]
    if not (name.endswith("-py3-none-any.whl") or name.endswith("-cp311-cp311-win_amd64.whl")):
        raise ValueError(f"Unsupported wheel tag: {name}")
    return path


def extract_wheel(path, target, seen):
    with zipfile.ZipFile(path) as archive:
        members = wheel_members(archive)
        wheel_metadata(archive, members, path.name)
        records = wheel_record(archive, members)
        for member in members:
            name = member.filename
            if name.casefold() in seen:
                raise ValueError(f"Bundle path collision: {name}")
            data = archive.read(member)
            verify_record(name, data, records[name])
            destination = target.joinpath(*PurePosixPath(name).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            seen.add(name.casefold())


def inventory(target):
    return [{"path": p.relative_to(target).as_posix(), "size": p.stat().st_size,
             "sha256": digest(p.read_bytes())} for p in sorted(target.rglob("*")) if p.is_file()]


def bundle_manifest(source_manifest, target):
    files = inventory(target)
    if not any(item["path"].lower().endswith(".pyd") for item in files):
        raise ValueError("Draft Skin bundle has no native modules")
    return {"schema": 1, "bundle": source_manifest["bundle"], "python": [3, 11],
            "platform": "win64", "blender": [5, 0, 1], "numpy": "1.26.4",
            "wheels": source_manifest["wheels"], "files": files}


def extract_sources(source, target, manifest):
    seen = set()
    for item in manifest["wheels"]:
        extract_wheel(verify_wheel_source(source, item), target, seen)


def verify_lock(manifest, payload, refresh_lock):
    if not refresh_lock and digest(payload) != manifest.get("bundle_lock_sha256"):
        raise ValueError("Bundle lock mismatch; bump version and explicitly refresh lock")


def source_manifest(source, refresh_lock, previous_bundle):
    manifest = json.loads((source / VENDOR / "manifest.json").read_text(encoding="utf-8"))
    if refresh_lock and (manifest.get("bundle_lock_sha256") or
                         not previous_bundle or previous_bundle == manifest["bundle"]):
        raise ValueError("Bump bundle version, remove old lock, provide --previous-bundle")
    return manifest


def build_bundle(source, target, refresh_lock=False, previous_bundle=None):
    manifest = source_manifest(source, refresh_lock, previous_bundle)
    if target.exists():
        raise FileExistsError(f"Bundle target already exists: {target}")
    target.mkdir(parents=True)
    try:
        extract_sources(source, target, manifest)
        payload = canonical(bundle_manifest(manifest, target))
        verify_lock(manifest, payload, refresh_lock)
        (target / "bundle.json").write_bytes(payload)
        return digest(payload)
    except Exception:
        shutil.rmtree(target)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--refresh-lock", action="store_true")
    parser.add_argument("--previous-bundle")
    args = parser.parse_args()
    if args.in_place == bool(args.target):
        parser.error("select exactly one of --target or --in-place")
    manifest = json.loads((args.source / VENDOR / "manifest.json").read_text())
    target = args.source / VENDOR / "bundles" / manifest["bundle"] if args.in_place else args.target
    print(build_bundle(args.source, target, args.refresh_lock, args.previous_bundle))


if __name__ == "__main__":
    main()
