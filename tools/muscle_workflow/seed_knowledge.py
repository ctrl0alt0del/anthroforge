"""Bootstrap maintained procedures; curate case evidence through remember."""

import json
import shutil
from pathlib import Path

from common import digest, read_json, reference, root, write_json
from knowledge import latest_records, remember

PROJECT = Path(__file__).resolve().parents[2]


def snapshot(source):
    path = PROJECT / source[8:] if source.startswith("project:") else Path(source)
    destination = root() / "knowledge" / "evidence" / (digest(path)[:16] + "-" + path.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copyfile(path, destination)
    return reference(destination, "Snapshot of " + str(path))


def seed_record(spec):
    spec = dict(spec)
    source = spec.pop("evidence_source")
    spec.update(schema_version=1, revision=1, evidence=[snapshot(source)])
    path = root() / "knowledge" / "bootstrap" / (spec["id"] + ".json")
    write_json(path, spec)
    return remember(path)


def main():
    existing = {item["id"] for item in latest_records()}
    records = read_json(Path(__file__).with_name("seed_lessons.json"))
    added = [seed_record(record) for record in records if record["id"] not in existing]
    return {"added": added, "previously_present": len(existing)}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
