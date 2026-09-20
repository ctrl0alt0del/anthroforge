"""Meaningful workflow contract checks runnable without Blender."""

from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, ValidationError

from tools.muscle_workflow import contracts


ARTIFACT = {"path": "E:/workflow/proof.json", "sha256": "a" * 64}
LESSON = {
    "schema_version": 1, "id": "retain-attachment", "revision": 1,
    "kind": "lesson", "status": "verified_case", "stages": ["base", "fibers"],
    "title": "Keep the attachment footprint", "observation": "A patch detached.",
    "action": "Preserve the measured footprint.", "applicability": "This fixture.",
    "limitations": "Other anatomy is untested.", "evidence": [ARTIFACT],
}
HANDOFF = {
    "schema_version": 1, "run_id": "trial-01", "stage": "base", "stage_revision": 1,
    "input_artifacts": [ARTIFACT], "output_artifacts": [ARTIFACT],
    "context_receipt": ARTIFACT, "librarian_brief": ARTIFACT,
    "observations": ["Footprint preserved."], "constraints": ["Retain insertion."],
    "checks": [{"name": "Footprint", "status": "pass", "evidence": [ARTIFACT]}],
    "status": "ready_for_downstream", "feedback_ids": [],
}
FEEDBACK = {
    "schema_version": 1, "id": "feedback-01", "run_id": "trial-01",
    "from_stage": "fibers", "to_stage": "base", "input_artifacts": [ARTIFACT],
    "affected": {"muscle": "temporalis", "head": None, "patch": None, "station": None},
    "expected": "Preserved footprint.", "observed": "Detached insertion.",
    "hypothesis": "The patch moved.", "request": "Restore insertion constraints.",
    "preserve_constraints": ["Retain origin."], "acceptance_check": "No detached ends.",
    "evidence": [ARTIFACT], "attempt": 1, "strategy_id": "restore-patch", "status": "open",
}
LIBRARIAN_BRIEF = {
    "schema_version": 1, "run_id": "trial-01", "input_artifacts": [ARTIFACT],
    "context_receipt": ARTIFACT,
    "observations": [{"feature": "Footprint", "basis": "observed", "evidence": [ARTIFACT]}],
    "lessons": [{"id": "retain-attachment", "revision": 1,
                 "reason": "Same affected patch.", "limits": "Fixture specific."}],
    "stage_actions": {"base": ["Retain insertion."]}, "unresolved_questions": [],
}
RECORDS = {"lesson": LESSON, "handoff": HANDOFF, "feedback": FEEDBACK,
           "librarian_brief": LIBRARIAN_BRIEF}


class ContractValidationTests(unittest.TestCase):
    def test_all_schemas_are_well_formed(self):
        for schema in contracts.SCHEMAS.values():
            Draft202012Validator.check_schema(schema)

    def test_valid_records_return_same_object_without_file_reads(self):
        with patch.object(Path, "open", side_effect=AssertionError("Unexpected IO")):
            for kind, fixture in RECORDS.items():
                with self.subTest(kind=kind):
                    record = deepcopy(fixture)
                    self.assertIs(contracts.validate_record(record, kind), record)

    def test_every_required_field_is_enforced(self):
        for kind, fixture in RECORDS.items():
            for field in contracts.SCHEMAS[kind]["required"]:
                with self.subTest(kind=kind, field=field):
                    record = deepcopy(fixture)
                    del record[field]
                    with self.assertRaises(ValidationError):
                        contracts.validate_record(record, kind)

    def test_unknown_core_fields_are_rejected_but_metadata_is_allowed(self):
        for kind, fixture in RECORDS.items():
            with self.subTest(kind=kind):
                record = deepcopy(fixture)
                record["metadata"] = {"experiment": {"custom": True}}
                contracts.validate_record(record, kind)
                record["observatons"] = []
                with self.assertRaises(ValidationError):
                    contracts.validate_record(record, kind)

    def test_unknown_record_kind_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown workflow record kind"):
            contracts.validate_record(LESSON, "lessons")

    def test_wrong_schema_versions_are_rejected(self):
        for kind, fixture in RECORDS.items():
            for version in (0, 2, True, "1"):
                with self.subTest(kind=kind, version=version):
                    record = {**deepcopy(fixture), "schema_version": version}
                    with self.assertRaises(ValidationError):
                        contracts.validate_record(record, kind)

    def test_required_evidence_cannot_be_empty(self):
        for status in ("requirement", "verified_case", "rejected"):
            with self.subTest(status=status):
                record = {**deepcopy(LESSON), "status": status, "evidence": []}
                with self.assertRaises(ValidationError):
                    contracts.validate_record(record, "lesson")

    def test_unverified_lessons_allow_empty_evidence(self):
        for status in ("hypothesis", "superseded"):
            record = {**deepcopy(LESSON), "status": status, "evidence": []}
            contracts.validate_record(record, "lesson")

    def test_lesson_identifiers_revisions_and_stages_are_constrained(self):
        changes = [{"id": "Not a slug"}, {"id": "slug\n"}, {"revision": 0},
                   {"revision": True}, {"revision": 1.5}, {"stages": []},
                   {"stages": ["base", "base"]}, {"stages": ["render"]}]
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(ValidationError):
                    contracts.validate_record({**deepcopy(LESSON), **change}, "lesson")
        contracts.validate_record({**deepcopy(LESSON), "stages": ["all"]}, "lesson")

    def test_blank_claims_are_rejected(self):
        for field in ("title", "observation", "action", "applicability", "limitations"):
            with self.subTest(field=field):
                record = {**deepcopy(LESSON), field: " \n "}
                with self.assertRaises(ValidationError):
                    contracts.validate_record(record, "lesson")

    def test_absolute_windows_and_posix_paths_are_supported(self):
        for path in ("E:/workflow/proof.json", r"C:\work\proof.json", "/tmp/proof.json",
                     r"\\server\share\proof.json"):
            with self.subTest(path=path):
                record = deepcopy(LESSON)
                record["evidence"][0]["path"] = path
                contracts.validate_record(record, "lesson")

    def test_relative_and_invalid_paths_are_rejected(self):
        for path in ("proof.json", "../proof.json", "C:proof.json", "", "/tmp/\x00file"):
            with self.subTest(path=path):
                record = deepcopy(LESSON)
                record["evidence"][0]["path"] = path
                with self.assertRaises(ValidationError):
                    contracts.validate_record(record, "lesson")

    def test_artifact_hashes_require_exact_hex_digest(self):
        for digest in ("a" * 63, "a" * 65, "g" * 64, "a" * 64 + "\n", 1):
            with self.subTest(digest=digest):
                record = deepcopy(LESSON)
                record["evidence"][0]["sha256"] = digest
                with self.assertRaises(ValidationError):
                    contracts.validate_record(record, "lesson")

    def test_nested_artifact_fields_are_strict(self):
        record = deepcopy(LESSON)
        record["evidence"][0]["checksum"] = "a" * 64
        with self.assertRaises(ValidationError):
            contracts.validate_record(record, "lesson")

    def test_ready_handoff_rejects_failed_or_unresolved_checks(self):
        for status in ("fail", "unresolved"):
            with self.subTest(status=status):
                record = deepcopy(HANDOFF)
                record["checks"][0]["status"] = status
                with self.assertRaises(ValidationError):
                    contracts.validate_record(record, "handoff")

    def test_ready_handoff_needs_checks_and_outputs(self):
        for field in ("checks", "output_artifacts"):
            with self.subTest(field=field):
                record = {**deepcopy(HANDOFF), field: []}
                with self.assertRaises(ValidationError):
                    contracts.validate_record(record, "handoff")

    def test_repair_handoff_can_report_failure_without_output(self):
        record = {**deepcopy(HANDOFF), "status": "repair_requested", "output_artifacts": []}
        record["checks"][0]["status"] = "fail"
        contracts.validate_record(record, "handoff")

    def test_not_applicable_check_is_allowed_in_ready_handoff(self):
        record = deepcopy(HANDOFF)
        record["checks"][0] = {"name": "Mirroring", "status": "not_applicable", "evidence": []}
        contracts.validate_record(record, "handoff")

    def test_handoff_check_typos_and_invalid_stages_are_rejected(self):
        record = deepcopy(HANDOFF)
        record["checks"][0]["status"] = "passed"
        with self.assertRaises(ValidationError):
            contracts.validate_record(record, "handoff")
        record = {**deepcopy(HANDOFF), "stage": "all"}
        with self.assertRaises(ValidationError):
            contracts.validate_record(record, "handoff")

    def test_feedback_requires_a_positive_attempt(self):
        for attempt in (0, -1, True, 1.5, "1"):
            with self.subTest(attempt=attempt):
                record = {**deepcopy(FEEDBACK), "attempt": attempt}
                with self.assertRaises(ValidationError):
                    contracts.validate_record(record, "feedback")

    def test_feedback_accepts_null_scope_and_named_numeric_stations(self):
        for station in (None, "distal", 0, 0.75):
            with self.subTest(station=station):
                record = deepcopy(FEEDBACK)
                record["affected"]["station"] = station
                contracts.validate_record(record, "feedback")

    def test_feedback_requires_explicit_affected_scope(self):
        for field in ("muscle", "head", "patch", "station"):
            with self.subTest(field=field):
                record = deepcopy(FEEDBACK)
                del record["affected"][field]
                with self.assertRaises(ValidationError):
                    contracts.validate_record(record, "feedback")

    def test_feedback_unknown_scope_and_missing_constraints_are_rejected(self):
        record = deepcopy(FEEDBACK)
        record["affected"]["patches"] = []
        with self.assertRaises(ValidationError):
            contracts.validate_record(record, "feedback")
        record = deepcopy(FEEDBACK)
        del record["preserve_constraints"]
        with self.assertRaises(ValidationError):
            contracts.validate_record(record, "feedback")

    def test_observed_brief_feature_requires_evidence(self):
        record = deepcopy(LIBRARIAN_BRIEF)
        record["observations"][0]["evidence"] = []
        with self.assertRaises(ValidationError):
            contracts.validate_record(record, "librarian_brief")

    def test_unknown_and_inferred_features_allow_empty_evidence(self):
        for basis in ("unknown", "inferred"):
            record = deepcopy(LIBRARIAN_BRIEF)
            record["observations"][0].update(basis=basis, evidence=[])
            contracts.validate_record(record, "librarian_brief")

    def test_brief_rejects_unknown_action_stage_and_unpinned_lesson(self):
        record = deepcopy(LIBRARIAN_BRIEF)
        record["stage_actions"]["render"] = ["Publish."]
        with self.assertRaises(ValidationError):
            contracts.validate_record(record, "librarian_brief")
        record = deepcopy(LIBRARIAN_BRIEF)
        del record["lessons"][0]["revision"]
        with self.assertRaises(ValidationError):
            contracts.validate_record(record, "librarian_brief")


class ArtifactVerificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "evidence.bin"
        self.path.write_bytes(b"preserved input bytes")
        self.artifact = {"path": str(self.path),
                         "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest()}

    def test_verification_returns_the_record(self):
        record = {"evidence": [self.artifact]}
        self.assertIs(contracts.verify_artifacts(record), record)

    def test_changed_artifact_is_rejected(self):
        self.path.write_bytes(b"modified input bytes")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            contracts.verify_artifacts({"evidence": [self.artifact]})

    def test_missing_artifact_is_rejected(self):
        self.path.unlink()
        with self.assertRaisesRegex(ValueError, "existing absolute file"):
            contracts.verify_artifacts({"evidence": [self.artifact]})

    def test_directory_is_rejected(self):
        self.artifact["path"] = self.directory.name
        with self.assertRaisesRegex(ValueError, "existing absolute file"):
            contracts.verify_artifacts({"evidence": [self.artifact]})

    def test_uppercase_digest_is_supported(self):
        self.artifact["sha256"] = self.artifact["sha256"].upper()
        contracts.verify_artifacts({"evidence": [self.artifact]})

    def test_nested_metadata_references_are_verified(self):
        record = {"evidence": [deepcopy(self.artifact)],
                  "metadata": {"nested": [{"more": deepcopy(self.artifact)}]}}
        contracts.verify_artifacts(record)
        record["metadata"]["nested"][0]["more"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            contracts.verify_artifacts(record)

    def test_relative_path_is_rejected_before_reading(self):
        self.artifact["path"] = "evidence.bin"
        with self.assertRaises(ValidationError):
            contracts.verify_artifacts({"evidence": [self.artifact]})

    def test_unreadable_artifact_is_reported(self):
        with patch.object(Path, "open", side_effect=PermissionError("Denied")):
            with self.assertRaisesRegex(ValueError, "Cannot read artifact"):
                contracts.verify_artifacts({"evidence": [self.artifact]})


if __name__ == "__main__":
    unittest.main()
