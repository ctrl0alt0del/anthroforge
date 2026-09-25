"""Behavioral tests for immutable knowledge and current-context handoffs."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import knowledge
from common import reference, write_json
from runs import initialize, context_inputs
from workflow import check_brief_context, check_handoff_context


def lesson(evidence):
    return dict(schema_version=1, id="test-evidence", revision=1, kind="lesson",
                status="verified_case", stages=["fibers"], title="Test fixture",
                observation="Observed geometry in fixture.", action="Inspect its boundary.",
                applicability="This fixture only.", limitations="No anatomical claim.",
                evidence=[reference(evidence)], card=dict(when="A boundary needs review.",
                    do="Inspect its boundary.", check="Compare the actual geometry.",
                    limits="This fixture only.", basis="case_observation", topic="boundary",
                    tags=["free-fibers"], category="modeling"))


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.addCleanup(patch.stopall)
        patch.dict("os.environ", AF_MUSCLE_WORKFLOW_HOME=str(self.directory)).start()
        (self.directory / "knowledge" / "lessons").mkdir(parents=True)
        self.index = patch.object(knowledge, "collection", return_value=MagicMock()).start()
        patch("runs.run_provenance", return_value={"approach_id": "test"}).start()
        self.evidence = self.directory / "geometry.json"
        self.evidence.write_text('{"actual":"geometry fixture"}', encoding="utf-8")

    def remember(self, item):
        path = write_json(self.directory / "incoming.json", item)
        return knowledge.remember(path)

    def test_idempotent_ingestion_and_revision_history(self):
        item = lesson(self.evidence)
        self.remember(item)
        self.remember(item)
        item.update(revision=2, observation="Revised after new measurement.")
        self.remember(item)
        files = list((self.directory / "knowledge" / "lessons" / item["id"]).glob("*.json"))
        self.assertEqual(len(files), 2)
        self.assertEqual(knowledge.latest_records()[0]["revision"], 2)

    def test_cannot_overwrite_a_lesson_revision(self):
        item = lesson(self.evidence)
        self.remember(item)
        item["observation"] = "Different claim without version change."
        with self.assertRaises(ValueError):
            self.remember(item)

    def test_changed_evidence_cannot_be_promoted(self):
        item = lesson(self.evidence)
        self.evidence.write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.remember(item)
        self.assertFalse(knowledge.latest_records())

    def test_mandatory_procedure_does_not_depend_on_semantic_match(self):
        item = lesson(self.evidence)
        item.update(kind="procedure", status="requirement")
        self.remember(item)
        patch.object(knowledge, "synchronize").start()
        patch.object(knowledge, "semantic_records", return_value=[]).start()
        result = knowledge.retrieve("fibers", "No diagnosed anatomical feature")
        self.assertEqual(result["procedures"][0]["id"], item["id"])
        self.assertEqual(result["lessons"], [])

    def test_superseded_procedure_is_not_injected(self):
        item = lesson(self.evidence)
        item.update(kind="procedure", status="superseded")
        self.remember(item)
        patch.object(knowledge, "synchronize").start()
        patch.object(knowledge, "semantic_records", return_value=[]).start()
        with self.assertRaises(ValueError):
            knowledge.retrieve("fibers", "anything")

    def test_retrieval_outage_preserves_required_procedure(self):
        item = lesson(self.evidence)
        item.update(kind="procedure", status="requirement")
        self.remember(item)
        self.index.side_effect = ConnectionError("Local service unavailable")
        result = knowledge.retrieve("fibers", "anything")
        self.assertEqual(result["procedures"][0]["id"], item["id"])
        self.assertEqual(result["retrieval_status"], "unavailable")
        self.assertEqual(result["lessons"], [])

    def test_hypothesis_cannot_become_mandatory_procedure(self):
        item = lesson(self.evidence)
        item.update(kind="procedure", status="hypothesis")
        self.remember(item)
        patch.object(knowledge, "synchronize").start()
        patch.object(knowledge, "semantic_records", return_value=[]).start()
        with self.assertRaises(ValueError):
            knowledge.retrieve("fibers", "anything")

    def test_stage_scope_is_respected(self):
        item = lesson(self.evidence)
        item.update(kind="procedure", status="requirement")
        self.remember(item)
        patch.object(knowledge, "synchronize").start()
        patch.object(knowledge, "semantic_records", return_value=[]).start()
        with self.assertRaises(ValueError):
            knowledge.retrieve("transfer", "anything")

    def test_changed_run_source_needs_new_manifest(self):
        manifest = initialize("test", self.evidence)
        self.evidence.write_text("new source", encoding="utf-8")
        with self.assertRaises(ValueError):
            context_inputs(manifest, [])

    def test_brief_rejects_nonexistent_recalled_lesson(self):
        packet = dict(run_id="test", input_artifacts=[reference(self.evidence)])
        receipt = reference(write_json(self.directory / "context.json", packet))
        brief = dict(**packet, context_receipt=receipt,
                     lessons=[dict(id="imaginary-lesson", revision=1)])
        with self.assertRaises(ValueError):
            check_brief_context(brief)

    def test_brief_rejects_mismatched_receipt_inputs(self):
        packet = dict(run_id="test", input_artifacts=[reference(self.evidence)])
        receipt = reference(write_json(self.directory / "context.json", packet))
        brief = dict(run_id="test", input_artifacts=[], context_receipt=receipt, lessons=[])
        with self.assertRaises(ValueError):
            check_brief_context(brief)

    def test_different_stage_inputs_invalidate_librarian_brief(self):
        inputs = [reference(self.evidence)]
        packet = dict(stage="fibers", run_id="test", input_artifacts=inputs)
        receipt = reference(write_json(self.directory / "context.json", packet))
        brief = dict(schema_version=1, run_id="test", input_artifacts=inputs,
                     context_receipt=receipt, observations=[], lessons=[],
                     stage_actions={"fibers": ["Measure width."]}, unresolved_questions=[])
        record = dict(stage="fibers", run_id="test", input_artifacts=inputs,
                      context_receipt=receipt,
                      librarian_brief=reference(write_json(self.directory / "brief.json", brief)))
        check_handoff_context(record)
        record["input_artifacts"] = []
        with self.assertRaises(ValueError):
            check_handoff_context(record)


if __name__ == "__main__":
    unittest.main()
