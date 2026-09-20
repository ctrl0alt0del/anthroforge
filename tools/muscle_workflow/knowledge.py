"""Versioned evidence records are authoritative; Chroma is a rebuildable index."""

import hashlib
import json

from filelock import FileLock

from common import COLLECTION, STAGES, read_json, reference, root, write_json
from contracts import validate_record, verify_artifacts
from service import client


def latest_records():
    records = []
    for directory in sorted((root() / "knowledge" / "lessons").iterdir()):
        versions = sorted(directory.glob("r[0-9]*.json")) if directory.is_dir() else []
        if versions:
            records.append(read_json(versions[-1]))
    return records


def collection():
    return client().get_or_create_collection(COLLECTION,
        metadata={"schema_version": 1, "authority": "knowledge/lessons"})


def indexed_text(record):
    fields = ("title", "observation", "action", "applicability", "limitations")
    return "\n".join(f"{field}: {record[field]}" for field in fields)


def metadata(record):
    result = {key: record[key] for key in ("id", "revision", "kind", "status", "title")}
    for stage in STAGES:
        result["stage_" + stage] = "all" in record["stages"] or stage in record["stages"]
    result["record_path"] = (root() / "knowledge" / "lessons" / record["id"] /
                             f"r{record['revision']:06d}.json").as_posix()
    return result


def upsert(index, records):
    if records:
        index.upsert(ids=[item["id"] for item in records],
                     documents=[indexed_text(item) for item in records],
                     metadatas=[metadata(item) for item in records])


def synchronize(index, records):
    existing = index.get(include=["metadatas"])
    versions = {key: value.get("revision") for key, value in
                zip(existing["ids"], existing["metadatas"])}
    changed = [item for item in records if versions.get(item["id"]) != item["revision"]]
    upsert(index, changed)


def bind_evidence(record):
    for evidence in record["evidence"]:
        current = reference(evidence["path"], evidence.get("claim"))
        if evidence.get("sha256", current["sha256"]) != current["sha256"]:
            raise ValueError("Evidence changed before ingestion: " + evidence["path"])
        evidence.update(current)
    return record


def require_next_revision(record, existing):
    previous = next((item for item in existing if item["id"] == record["id"]), None)
    if previous == record:
        return False
    expected = previous["revision"] + 1 if previous else 1
    if record["revision"] != expected:
        raise ValueError(f"Expected revision {expected} for {record['id']}")
    return True


def remember(path):
    record = bind_evidence(read_json(path))
    validate_record(record, "lesson")
    verify_artifacts(record)
    with FileLock(str(root() / "knowledge" / "curation.lock"), timeout=120):
        if require_next_revision(record, latest_records()):
            write_json(metadata(record)["record_path"], record)
        upsert(collection(), [record])
    return {"id": record["id"], "revision": record["revision"], "indexed": True}


def reindex():
    with FileLock(str(root() / "knowledge" / "curation.lock"), timeout=120):
        records = latest_records()
        for record in records:
            validate_record(record, "lesson")
        upsert(collection(), records)
    return {"indexed": len(records)}


def applicable(record, stage):
    return record["status"] != "superseded" and (
        "all" in record["stages"] or stage in record["stages"])


def memory_digest(records):
    payload = json.dumps(records, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def semantic_records(index, stage, query, records, limit):
    where = {"$and": [{"stage_" + stage: True}, {"kind": "lesson"},
                       {"status": {"$ne": "superseded"}}]}
    if not records:
        return []
    matches = index.query(query_texts=[query], n_results=min(limit, len(records)), where=where)
    by_id = {item["id"]: item for item in records}
    return [dict(by_id[key], retrieval_distance=distance) for key, distance in
            zip(matches["ids"][0], matches["distances"][0]) if key in by_id]


def retrieve_indexed(stage, query, records, limit):
    try:
        index = collection()
        synchronize(index, records)
        lessons = [r for r in records if r["kind"] == "lesson" and applicable(r, stage)]
        matches = semantic_records(index, stage, query, lessons, limit)
        return {"lessons": matches, "retrieval_status": "available"}
    except Exception as error:
        return {"lessons": [], "retrieval_status": "unavailable", "retrieval_error": str(error)}


def retrieve(stage, query, limit=6):
    with FileLock(str(root() / "knowledge" / "curation.lock"), timeout=120):
        records = latest_records()
        mandatory = [r for r in records if r["kind"] == "procedure" and
                     r["status"] == "requirement" and applicable(r, stage)]
        indexed = retrieve_indexed(stage, query, records, limit)
    if not mandatory:
        raise ValueError("No stage procedure: seed the workflow before construction")
    return {"knowledge_digest": memory_digest(records), "procedures": mandatory,
            "query": query, "stage": stage, **indexed}
