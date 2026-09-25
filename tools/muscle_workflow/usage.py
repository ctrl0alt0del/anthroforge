"""Decision receipts distinguish retrieved advice from observed usefulness."""

from pathlib import Path
from uuid import uuid4

from common import now, read_json, reference, write_json
from contracts import validate_record, verify_artifacts
from runs import manifest_path


def check_usage(record):
    validate_record(record, "usage")
    verify_artifacts(record)
    packet = read_json(record["context_receipt"]["path"])
    if (packet["run_id"], packet["stage"]) != (record["run_id"], record["stage"]):
        raise ValueError("Usage must match the run and stage of its context receipt")
    available = {(r["id"], r["revision"]) for r in packet["procedures"] + packet["lessons"]}
    seen = set()
    for item in record["lessons"]:
        key = item["id"], item["revision"]
        if key not in available or key in seen:
            raise ValueError("Lesson was not retrieved at this revision, or is duplicated")
        seen.add(key)
        if item["effect"] in ("helped", "neutral", "harmed") and not item["evidence"]:
            raise ValueError("Observed usefulness needs evidence; otherwise use unknown/not_tested")


def record_usage(run, path):
    manifest = manifest_path(run)
    record = read_json(path)
    check_usage(record)
    receipt_path = Path(record["context_receipt"]["path"]).resolve()
    if record["run_id"] != read_json(manifest)["run_id"] or not receipt_path.is_relative_to(manifest.parent):
        raise ValueError("Usage context belongs to another run directory")
    record.setdefault("metadata", {})["recorded_at"] = now()
    destination = manifest.parent / "knowledge/usage" / (uuid4().hex + ".json")
    return {"usage_receipt": reference(write_json(destination, record))}


def usage_summary(run):
    directory = manifest_path(run).parent / "knowledge/usage"
    records = [read_json(path) for path in sorted(directory.glob("*.json"))]
    notes = [item for record in records for item in record["lessons"]]
    effects = {key: sum(n["effect"] == key for n in notes)
               for key in ("helped", "neutral", "harmed", "unknown", "not_tested")}
    return {"receipts": len(records), "decision_notes": len(notes), "effects": effects,
            "scope": "Recorded observations, not a causal benefit score or count of unique lessons"}
