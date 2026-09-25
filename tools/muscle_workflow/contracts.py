"""Strict, offline workflow contracts; validation does not certify anatomy."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath, PureWindowsPath

from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_VERSION = 1
STAGES = ("transfer", "base", "fibers", "inflation", "review")
TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
SLUG = {"type": "string", "pattern": r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        "not": {"pattern": r"[\r\n]"}}
POSITIVE_INTEGER = {"type": "integer", "minimum": 1}
STAGE = {"enum": list(STAGES)}
FORMAT_CHECKER = FormatChecker()


@FORMAT_CHECKER.checks("absolute-path")
def _absolute_path(value):
    """Accept absolute Windows or POSIX paths without touching the filesystem."""
    if not isinstance(value, str) or "\x00" in value:
        return False
    return PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute()


def _array(items, minimum=0, unique=False):
    return {"type": "array", "items": items, "minItems": minimum,
            "uniqueItems": unique}


def _object(properties, optional=()):
    return {"type": "object", "properties": properties,
            "required": [key for key in properties if key not in optional],
            "additionalProperties": False}


ARTIFACT_SCHEMA = _object({
    "path": {**TEXT, "format": "absolute-path"},
    "sha256": {"type": "string", "minLength": 64, "maxLength": 64,
               "pattern": "^[a-fA-F0-9]{64}$"},
    "claim": TEXT,
}, optional=("claim",))
ARTIFACT = {"$ref": "#/$defs/artifact"}
ARTIFACTS = _array(ARTIFACT)
STRINGS = _array(TEXT)


def _record(kind, properties, conditions=()):
    base = {"schema_version": {"type": "integer", "const": SCHEMA_VERSION}}
    schema = _object({**base, **properties, "metadata": {"type": "object"}},
                     optional=("metadata",))
    schema.update({"$schema": "https://json-schema.org/draft/2020-12/schema",
                   "$id": f"urn:anthroforge:muscle-workflow:{kind}:v1",
                   "$defs": {"artifact": ARTIFACT_SCHEMA}})
    if conditions:
        schema["allOf"] = list(conditions)
    return schema


CARD_SCHEMA = _object({
    "when": TEXT, "do": TEXT, "check": TEXT, "limits": TEXT,
    "basis": {"enum": ["user_requirement", "case_observation", "repeated_observation", "hypothesis"]},
    "topic": SLUG, "tags": _array(SLUG, minimum=1, unique=True),
    "category": {"enum": ["modeling", "engineering", "history"]},
})

LESSON_SCHEMA = _record("lesson", {
    "id": SLUG,
    "revision": POSITIVE_INTEGER,
    "kind": {"enum": ["procedure", "lesson"]},
    "status": {"enum": ["requirement", "verified_case", "hypothesis",
                         "rejected", "superseded"]},
    "stages": _array({"enum": [*STAGES, "all"]}, minimum=1, unique=True),
    "title": TEXT,
    "observation": TEXT,
    "action": TEXT,
    "applicability": TEXT,
    "limitations": TEXT,
    "evidence": ARTIFACTS,
}, conditions=({
    "if": {"properties": {"status": {"enum": ["requirement", "verified_case",
                                                "rejected"]}},
           "required": ["status"]},
    "then": {"properties": {"evidence": {"minItems": 1}}},
},))
LESSON_SCHEMA["properties"]["card"] = CARD_SCHEMA

CHECK_SCHEMA = _object({
    "name": TEXT,
    "status": {"enum": ["pass", "fail", "unresolved", "not_applicable"]},
    "evidence": ARTIFACTS,
})
HANDOFF_SCHEMA = _record("handoff", {
    "run_id": TEXT,
    "stage": STAGE,
    "stage_revision": POSITIVE_INTEGER,
    "input_artifacts": ARTIFACTS,
    "output_artifacts": ARTIFACTS,
    "context_receipt": ARTIFACT,
    "librarian_brief": ARTIFACT,
    "observations": STRINGS,
    "checks": _array(CHECK_SCHEMA),
    "status": {"enum": ["ready_for_downstream", "repair_requested", "rejected"]},
    "feedback_ids": STRINGS,
    "constraints": STRINGS,
}, conditions=({
    "if": {"properties": {"status": {"const": "ready_for_downstream"}},
           "required": ["status"]},
    "then": {"properties": {
        "output_artifacts": {"minItems": 1},
        "checks": {"minItems": 1, "items": {"properties": {
            "status": {"enum": ["pass", "not_applicable"]}}}},
    }},
},))

NULLABLE_TEXT = {"anyOf": [TEXT, {"type": "null"}]}
AFFECTED_SCHEMA = _object({
    "muscle": TEXT,
    "head": NULLABLE_TEXT,
    "patch": NULLABLE_TEXT,
    "station": {"anyOf": [TEXT, {"type": "number"}, {"type": "null"}]},
})
FEEDBACK_SCHEMA = _record("feedback", {
    "id": TEXT,
    "run_id": TEXT,
    "from_stage": STAGE,
    "to_stage": STAGE,
    "input_artifacts": ARTIFACTS,
    "affected": AFFECTED_SCHEMA,
    "expected": TEXT,
    "observed": TEXT,
    "hypothesis": TEXT,
    "request": TEXT,
    "preserve_constraints": STRINGS,
    "acceptance_check": TEXT,
    "evidence": ARTIFACTS,
    "attempt": POSITIVE_INTEGER,
    "strategy_id": TEXT,
    "status": {"enum": ["open", "answered", "resolved"]},
})

OBSERVATION_SCHEMA = _object({
    "feature": TEXT,
    "basis": {"enum": ["observed", "inferred", "unknown"]},
    "evidence": ARTIFACTS,
})
OBSERVATION_SCHEMA["allOf"] = [{
    "if": {"properties": {"basis": {"const": "observed"}},
           "required": ["basis"]},
    "then": {"properties": {"evidence": {"minItems": 1}}},
}]
LESSON_REFERENCE_SCHEMA = _object({
    "id": SLUG,
    "revision": POSITIVE_INTEGER,
    "reason": TEXT,
    "limits": TEXT,
})
STAGE_ACTIONS_SCHEMA = _object({stage: STRINGS for stage in STAGES}, optional=STAGES)
LIBRARIAN_BRIEF_SCHEMA = _record("librarian_brief", {
    "run_id": TEXT,
    "input_artifacts": ARTIFACTS,
    "context_receipt": ARTIFACT,
    "observations": _array(OBSERVATION_SCHEMA),
    "lessons": _array(LESSON_REFERENCE_SCHEMA),
    "stage_actions": STAGE_ACTIONS_SCHEMA,
    "unresolved_questions": STRINGS,
})

USAGE_SCHEMA = _record("usage", {
    "run_id": TEXT, "stage": STAGE, "context_receipt": ARTIFACT,
    "lessons": _array(_object({
        "id": SLUG, "revision": POSITIVE_INTEGER,
        "disposition": {"enum": ["applied", "adapted", "not_applicable", "skipped"]},
        "decision": TEXT, "result": TEXT,
        "effect": {"enum": ["helped", "neutral", "harmed", "unknown", "not_tested"]},
        "evidence": ARTIFACTS,
    }), minimum=1),
})

SCHEMAS = {
    "lesson": LESSON_SCHEMA,
    "feedback": FEEDBACK_SCHEMA,
    "handoff": HANDOFF_SCHEMA,
    "librarian_brief": LIBRARIAN_BRIEF_SCHEMA,
    "usage": USAGE_SCHEMA,
}


def _validator(schema):
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FORMAT_CHECKER)


VALIDATORS = {kind: _validator(schema) for kind, schema in SCHEMAS.items()}
ARTIFACT_VALIDATOR = _validator(ARTIFACT_SCHEMA)


def validate_record(record, kind):
    """Return the same record after schema checks; never read artifact files."""
    if kind not in VALIDATORS:
        raise ValueError(f"Unknown workflow record kind: {kind!r}")
    VALIDATORS[kind].validate(record)
    return record


def _artifact_refs(value):
    if isinstance(value, dict):
        if {"path", "sha256"}.issubset(value):
            yield value
        for child in value.values():
            yield from _artifact_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _artifact_refs(child)


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_artifact(artifact):
    ARTIFACT_VALIDATOR.validate(artifact)
    path = Path(artifact["path"])
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"Artifact must be an existing absolute file: {path}")
    try:
        actual = _file_sha256(path)
    except OSError as error:
        raise ValueError(f"Cannot read artifact: {path}") from error
    if actual != artifact["sha256"].lower():
        raise ValueError(f"Artifact SHA-256 mismatch: {path}")


def verify_artifacts(record):
    """Check bytes for every embedded reference; validate the record separately."""
    for artifact in _artifact_refs(record):
        _verify_artifact(artifact)
    return record
