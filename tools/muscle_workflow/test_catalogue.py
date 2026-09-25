"""Completion cannot leak from old candidates or unversioned configurations."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import ValidationError

from catalogue import catalogue_summary, save_catalogue, validate_catalogue
from common import reference, write_json


def fixture(artifact):
    approach = dict(id="test-v1", description="Test", recorded_at="2026-09-24",
                    scope="Fixture", stages={s: "Test" for s in ("transfer", "base_fibers", "inflation")}, evidence=[artifact])
    family = dict(id="biceps", name="Biceps", group="arm", definition={}, sides=["L", "R"],
                  status="queued", current_stage=None, current_build=None, historical_runs=[], remaining_work=["Build"])
    return dict(schema_version=2, revision=1, updated_at="2026-09-24", source_catalogue=artifact,
                acceptance_policy="Only explicit acceptance", policy_evidence=[artifact],
                current_approach_id="test-v1", approaches=[approach], families=[family],
                next_selection=dict(family_id="biceps", side="L", approach_id="test-v1", reason="Next"))


def accepted_build(artifact):
    return dict(run_id="test", approach_id="test-v1", authored_sides=["L"], mirrored_sides=["R"],
        methods={s: dict(version="v1", description="Test") for s in ("transfer", "base_fibers", "inflation")},
        authoring=dict(protocol_version="0.4.0", git_commit=None, source_manifest=None,
                       native_build=None, provenance="not_recorded", note="Historical"),
        blend=artifact, journal=dict(path="E:/journal", manifest=artifact),
        acceptance=dict(status="user_accepted", scope="Fixture", evidence=[artifact]), technical_review=[artifact])


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = patch.dict("os.environ", AF_MUSCLE_WORKFLOW_HOME=str(self.root))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.artifact = reference(write_json(self.root / "evidence.json", {"test": True}))
        self.record = fixture(self.artifact)

    def accepted(self):
        record = copy.deepcopy(self.record)
        record["next_selection"] = None
        record["families"][0].update(status="accepted", current_stage="complete",
                                      current_build=accepted_build(self.artifact))
        return record

    def test_old_candidate_without_acceptance_cannot_be_done(self):
        self.record["families"][0]["status"] = "accepted"
        with self.assertRaisesRegex(ValueError, "Accepted families require"):
            validate_catalogue(self.record)

    def test_missing_method_version_and_unknown_approach_are_rejected(self):
        record = self.accepted()
        del record["families"][0]["current_build"]["methods"]["transfer"]["version"]
        with self.assertRaises(ValidationError):
            validate_catalogue(record)
        record = self.accepted()
        record["families"][0]["current_build"]["approach_id"] = "unregistered"
        with self.assertRaisesRegex(ValueError, "Unknown build approach"):
            validate_catalogue(record)

    def test_capture_claim_requires_actual_manifest(self):
        record = self.accepted()
        record["families"][0]["current_build"]["authoring"]["provenance"] = "captured"
        with self.assertRaisesRegex(ValueError, "needs a source manifest"):
            validate_catalogue(record)

    def test_only_accepted_family_counts_despite_historical_runs(self):
        record = self.accepted()
        unfinished = copy.deepcopy(self.record["families"][0])
        unfinished.update(id="triceps", historical_runs=[self.artifact], status="needs_rebuild")
        record["families"].append(unfinished)
        path = write_json(self.root / "incoming.json", record)
        save_catalogue(path, 0)
        summary = catalogue_summary()
        self.assertEqual([r["id"] for r in summary["accepted"]], ["biceps"])
        self.assertEqual(summary["statuses"]["needs_rebuild"], 1)

    def test_revision_guard_preserves_old_catalogue_and_rejects_stale_write(self):
        path = write_json(self.root / "incoming.json", self.record)
        first = save_catalogue(path, 0)
        self.record["revision"] = 2
        write_json(path, self.record)
        with self.assertRaisesRegex(ValueError, "Catalogue changed"):
            save_catalogue(path, 0)
        save_catalogue(path, 1)
        self.assertEqual(reference(first["revision_record"]["path"]), first["revision_record"])

    def test_accepted_family_cannot_be_queued_as_unfinished(self):
        record = self.accepted()
        record["next_selection"] = self.record["next_selection"]
        with self.assertRaisesRegex(ValueError, "accepted muscle"):
            validate_catalogue(record)

    def test_acceptance_evidence_tampering_fails(self):
        record = self.accepted()
        write_json(self.artifact["path"], {"changed": True})
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            validate_catalogue(record)

    def test_reusing_an_approach_version_for_changed_method_is_rejected(self):
        path = write_json(self.root / "incoming.json", self.record)
        save_catalogue(path, 0)
        self.record["revision"] = 2
        self.record["approaches"][0]["stages"]["transfer"] = "Different algorithm"
        write_json(path, self.record)
        with self.assertRaisesRegex(ValueError, "immutable"):
            save_catalogue(path, 1)


if __name__ == "__main__":
    unittest.main()
