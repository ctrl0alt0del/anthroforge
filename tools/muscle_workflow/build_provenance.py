"""Fingerprint the local authoring source without claiming a loaded Blender build."""

import hashlib
import json
import subprocess
from pathlib import Path

from common import digest, now, read_json, reference, root, write_json

PROJECT = Path(__file__).resolve().parents[2]
CODE_ROOTS = {"adapters", "app", "core", "operators", "ui", "native", "properties", "utils", "vendor", "workers"}
SUFFIXES = {".py", ".cpp", ".h", ".hpp", ".dll", ".pyd", ".json"}


def git_output(*args):
    return subprocess.check_output(["git", *args], cwd=PROJECT).decode("utf-8").strip()


def source_files():
    names = git_output("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    paths = [Path(name) for name in names if name]
    return sorted({p for p in paths if p.suffix in SUFFIXES and
                   (len(p.parts) == 1 or p.parts[0] in CODE_ROOTS) and (PROJECT / p).is_file()})


def capture_authoring():
    files = [{"path": p.as_posix(), "sha256": digest(PROJECT / p)} for p in source_files()]
    head = git_output("rev-parse", "HEAD")
    fingerprint = hashlib.sha256(json.dumps(dict(files=files, git_commit=head), sort_keys=True).encode()).hexdigest()
    manifest = dict(captured_at=now(), git_commit=head,
                    working_tree_dirty=bool(git_output("status", "--porcelain")),
                    fingerprint=fingerprint, files=files, scope="Local source; loaded Blender code not attested")
    path = root() / "catalogue/builds" / (fingerprint + ".json")
    if not path.exists():
        write_json(path, manifest)
    return dict(protocol_version="0.4.0", git_commit=manifest["git_commit"],
                source_manifest=reference(path), native_build=None, provenance="captured",
                note="Local source fingerprint includes indexed native binaries; record active runtime build separately.")


def run_provenance():
    catalogue = root() / "catalogue/catalogue.json"
    approach = read_json(catalogue)["current_approach_id"] if catalogue.exists() else None
    return {"approach_id": approach, "authoring": capture_authoring(), "captured_at": now()}
