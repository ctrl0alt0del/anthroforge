"""Run directories and stage briefings bound to actual artifact versions."""

import re
from pathlib import Path
from uuid import uuid4

from common import STAGES, now, read_json, reference, root, verify_reference, write_json
from knowledge import retrieve


def initialize(name, source, target=None):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
    if not slug:
        raise ValueError("Run name must contain letters or digits")
    inputs = [reference(source)] + ([reference(target)] if target else [])
    run_id = now()[:10] + "-" + slug + "-" + uuid4().hex[:8]
    directory = root() / "runs" / run_id
    for part in (*STAGES, "inputs", "knowledge", "feedback", "logs", "tmp"):
        (directory / part).mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": 1, "run_id": run_id, "name": name, "created": now(),
                "input_artifacts": inputs, "status": "created", "accepted_candidate": None}
    return write_json(directory / "run.json", manifest)


def manifest_path(run):
    path = Path(run).resolve(strict=True)
    path = path / "run.json" if path.is_dir() else path
    if not path.is_relative_to(root() / "runs"):
        raise ValueError("Run must belong to this workflow artifact directory")
    return path


def context_inputs(manifest, extras):
    original = read_json(manifest)["input_artifacts"]
    for item in original:
        verify_reference(item)
    inputs = {item["path"]: item for item in original}
    inputs.update({str(Path(path).resolve().as_posix()): reference(path) for path in extras})
    return list(inputs.values())


def context(run, stage, query, extras=()):
    manifest = manifest_path(run)
    inputs = context_inputs(manifest, extras)
    packet = retrieve(stage, query)
    packet.update(schema_version=1, created=now(), run_id=read_json(manifest)["run_id"],
                  input_artifacts=inputs, run_manifest=reference(manifest))
    path = manifest.parent / "knowledge" / f"{stage}-{uuid4().hex[:12]}.json"
    write_json(path, packet)
    return {"receipt": reference(path), "briefing": packet}
