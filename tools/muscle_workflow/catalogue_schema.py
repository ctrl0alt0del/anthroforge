"""Versioned body-family progress, separate from lessons and historical run logs."""

from contracts import TEXT, ARTIFACT_SCHEMA, _array, _object, _validator

REF = {"$ref": "#/$defs/artifact"}
NULL_TEXT = {"anyOf": [TEXT, {"type": "null"}]}
NULL_REF = {"anyOf": [REF, {"type": "null"}]}
SIDES = _array({"enum": ["L", "R", "midline"]}, unique=True)
STAGES = ("transfer", "base_fibers", "inflation")
METHOD = _object({"version": TEXT, "description": TEXT})
AUTHORING = _object({"protocol_version": TEXT, "git_commit": NULL_TEXT,
    "source_manifest": NULL_REF, "native_build": NULL_TEXT,
    "provenance": {"enum": ["captured", "not_recorded"]}, "note": TEXT})
ACCEPTANCE = _object({"status": {"enum": ["user_accepted", "pending", "rejected"]},
    "scope": TEXT, "evidence": _array(REF, minimum=1)})
BUILD = _object({"run_id": TEXT, "approach_id": TEXT,
    "methods": _object({stage: METHOD for stage in STAGES}), "authoring": AUTHORING,
    "authored_sides": SIDES, "mirrored_sides": SIDES, "blend": REF,
    "journal": _object({"path": TEXT, "manifest": REF}), "acceptance": ACCEPTANCE,
    "technical_review": _array(REF, minimum=1)})
FAMILY = _object({"id": TEXT, "name": TEXT, "group": TEXT,
    "definition": {"type": "object"}, "sides": SIDES,
    "status": {"enum": ["not_started", "needs_rebuild", "queued", "in_progress", "ready_for_review", "accepted"]},
    "current_stage": {"enum": [None, *STAGES, "review", "complete"]},
    "current_build": {"anyOf": [BUILD, {"type": "null"}]},
    "historical_runs": _array(REF), "remaining_work": _array(TEXT)})
APPROACH = _object({"id": TEXT, "description": TEXT, "recorded_at": TEXT,
    "scope": TEXT, "stages": _object({stage: TEXT for stage in STAGES}),
    "evidence": _array(REF, minimum=1)})
SELECTION = _object({"family_id": TEXT, "side": {"enum": ["L", "R", "midline"]},
    "approach_id": TEXT, "reason": TEXT})
CATALOGUE_SCHEMA = _object({"schema_version": {"const": 2, "type": "integer"},
    "revision": {"type": "integer", "minimum": 1}, "updated_at": TEXT,
    "source_catalogue": REF, "acceptance_policy": TEXT, "policy_evidence": _array(REF, minimum=1),
    "current_approach_id": TEXT, "approaches": _array(APPROACH, minimum=1),
    "families": _array(FAMILY, minimum=1),
    "next_selection": {"anyOf": [SELECTION, {"type": "null"}]}})
CATALOGUE_SCHEMA.update({"$schema": "https://json-schema.org/draft/2020-12/schema",
                         "$defs": {"artifact": ARTIFACT_SCHEMA}})
VALIDATOR = _validator(CATALOGUE_SCHEMA)
