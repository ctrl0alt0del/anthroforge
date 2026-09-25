"""Central completion register with immutable revisions and explicit provenance."""

from collections import Counter
from pathlib import Path

from filelock import FileLock

from catalogue_schema import VALIDATOR
from common import read_json, reference, root, write_json
from contracts import verify_artifacts


def validate_build(family, approaches):
    build = family["current_build"]
    if family["status"] == "accepted":
        if not build or build["acceptance"]["status"] != "user_accepted" or family["current_stage"] != "complete":
            raise ValueError("Accepted families require an accepted build and complete stage")
    if build:
        if build["approach_id"] not in approaches:
            raise ValueError("Unknown build approach")
        covered = set(build["authored_sides"] + build["mirrored_sides"])
        if not covered or not covered.issubset(family["sides"]):
            raise ValueError("Build sides must belong to the family")
        if set(build["authored_sides"]).intersection(build["mirrored_sides"]):
            raise ValueError("A side cannot be both authored and a generated mirror")
        if build["authoring"]["provenance"] == "captured" and not build["authoring"]["source_manifest"]:
            raise ValueError("Captured authoring provenance needs a source manifest")


def validate_catalogue(record, artifacts=True):
    VALIDATOR.validate(record)
    families = {r["id"]: r for r in record["families"]}
    approaches = {r["id"] for r in record["approaches"]}
    if len(families) != len(record["families"]) or len(approaches) != len(record["approaches"]):
        raise ValueError("Duplicate family or approach identity")
    if record["current_approach_id"] not in approaches:
        raise ValueError("Unknown current approach")
    for family in families.values():
        validate_build(family, approaches)
    validate_selection(record["next_selection"], families, approaches)
    if artifacts:
        verify_artifacts(record)
    return record


def validate_selection(selection, families, approaches):
    if selection is None:
        return
    family = families.get(selection["family_id"])
    if not family or selection["side"] not in family["sides"] or selection["approach_id"] not in approaches:
        raise ValueError("Invalid next muscle selection")
    if family["status"] == "accepted":
        raise ValueError("An accepted muscle cannot be selected as unfinished work")


def save_catalogue(path, expected_revision):
    record = validate_catalogue(read_json(path))
    directory = root() / "catalogue"
    directory.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory / "catalogue.lock"), timeout=30):
        return publish_catalogue(directory, record, expected_revision)


def publish_catalogue(directory, record, expected_revision):
    current = directory / "catalogue.json"
    previous = read_json(current)["revision"] if current.exists() else 0
    if expected_revision != previous or record["revision"] != previous + 1:
        raise ValueError("Catalogue changed; use the next revision of the current register")
    preserve_approach_versions(read_json(current) if current.exists() else None, record)
    archive = directory / "revisions" / f"r{record['revision']:06d}.json"
    if archive.exists() and read_json(archive) != record:
        raise ValueError("Cannot overwrite an immutable catalogue revision")
    if not archive.exists():
        write_json(archive, record)
    write_json(current, record)
    return {"catalogue": reference(current), "revision_record": reference(archive)}


def preserve_approach_versions(previous, record):
    if previous is None:
        return
    current = {a["id"]: a for a in record["approaches"]}
    if any(current.get(a["id"]) != a for a in previous["approaches"]):
        raise ValueError("Published approach versions are immutable; register a new approach ID")


def catalogue_summary(path=None):
    record = validate_catalogue(read_json(path or root() / "catalogue/catalogue.json"), artifacts=False)
    accepted = [r for r in record["families"] if r["status"] == "accepted"]
    return {"revision": record["revision"], "current_approach": record["current_approach_id"],
            "family_count": len(record["families"]),
            "statuses": dict(Counter(r["status"] for r in record["families"])),
            "accepted": [{"id": r["id"], "run_id": r["current_build"]["run_id"],
                          "approach_id": r["current_build"]["approach_id"]} for r in accepted],
            "next": record["next_selection"]}
