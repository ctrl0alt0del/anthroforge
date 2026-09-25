"""Retrieval regressions from the real stage mismatch and oversized memories."""

import copy
import unittest
from unittest.mock import MagicMock, patch

import knowledge
from common import read_json, reference, write_json
from memory_cards import compact, select_diverse, validate_size
from runs import context, initialize
import test_workflow as fixtures
from usage import check_usage, record_usage

lesson = fixtures.lesson


class CardTests(unittest.TestCase):
    def test_oversize_card_cannot_hide_action_in_embedding_truncation(self):
        record = lesson(__file__)
        record["card"]["when"] = "long observation " * 260
        with self.assertRaisesRegex(ValueError, "shorten"):
            validate_size(record)

    def test_base_receives_fiber_only_lessons_but_transfer_does_not(self):
        record = lesson(__file__)
        self.assertTrue(knowledge.applicable(record, "base"))
        self.assertFalse(knowledge.applicable(record, "transfer"))
        self.assertTrue(knowledge.metadata(record)["stage_base"])

    def test_explicit_features_prioritize_a_condition_and_deduplicate_topic(self):
        records = [lesson(__file__) for _ in range(3)]
        for index, record in enumerate(records):
            record.update(id=f"lesson-{index}", retrieval_distance=index)
        records[2]["card"].update(topic="branch", tags=["branch"])
        selected = select_diverse(records, 3, ["branch"])
        self.assertEqual([r["id"] for r in selected], ["lesson-2", "lesson-0"])

    def test_embedding_version_change_forces_reindex_without_lesson_rewrite(self):
        index = MagicMock()
        record = lesson(__file__)
        index.get.return_value = {"ids": [record["id"]], "metadatas": [{"revision": 1}]}
        with patch.object(knowledge, "upsert") as update:
            knowledge.synchronize(index, [record])
            update.assert_called_once_with(index, [record])
        self.assertEqual(record["revision"], 1)


class StoredCardTests(unittest.TestCase):
    setUp = fixtures.WorkflowTests.setUp
    remember = fixtures.WorkflowTests.remember
    def setup_records(self):
        record = lesson(self.evidence)
        self.remember(record)
        procedure = copy.deepcopy(record)
        procedure.update(id="required-width", kind="procedure", status="requirement")
        self.remember(procedure)
        return record

    def test_compact_record_opens_exact_complete_case(self):
        record = self.setup_records()
        result = compact(record)
        self.assertNotIn("observation", result)
        self.assertEqual(read_json(result["case_record"]["path"]), record)
        self.assertEqual(knowledge.get_record(record["id"], 1), record)

    def test_engineering_records_do_not_enter_default_modeling_query(self):
        record = self.setup_records()
        record["card"]["category"] = "engineering"
        record["revision"] = 2
        self.remember(record)
        with patch.object(knowledge, "synchronize"), patch.object(knowledge, "semantic_records", return_value=[]) as query:
            knowledge.retrieve("base", "branch")
            self.assertEqual(query.call_args.args[3], [])
            knowledge.retrieve("base", "branch", category="engineering")
            self.assertEqual(query.call_args.args[3][0]["id"], record["id"])

    def test_new_revisions_need_curated_card_but_old_records_still_read(self):
        record = lesson(self.evidence)
        record.pop("card")
        with self.assertRaisesRegex(ValueError, "curated card"):
            self.remember(record)
        path = self.directory / "knowledge/lessons" / record["id"] / "r000001.json"
        write_json(path, record)
        self.assertEqual(knowledge.get_record(record["id"], 1), record)

    def packet(self):
        record = self.setup_records()
        manifest = initialize("usage-test", self.evidence)
        with patch.object(knowledge, "synchronize"), patch.object(knowledge, "semantic_records", return_value=[dict(record, retrieval_distance=0.1)]):
            packet = context(manifest, "base", "boundary")
        note = dict(id=record["id"], revision=1, disposition="applied",
                    decision="Kept the boundary.", result="Not yet evaluated.", effect="not_tested", evidence=[])
        usage = dict(schema_version=1, run_id=packet["briefing"]["run_id"], stage="base",
                     context_receipt=packet["receipt"], lessons=[note])
        return manifest, usage

    def test_application_receipt_is_immutable_and_bound_to_retrieval(self):
        manifest, usage = self.packet()
        incoming = write_json(self.directory / "usage.json", usage)
        first = record_usage(manifest, incoming)
        second = record_usage(manifest, incoming)
        self.assertNotEqual(first["usage_receipt"]["path"], second["usage_receipt"]["path"])
        check_usage(read_json(first["usage_receipt"]["path"]))

    def test_cannot_claim_unretrieved_revision_or_unobserved_benefit(self):
        _, usage = self.packet()
        usage["lessons"][0]["revision"] = 2
        with self.assertRaisesRegex(ValueError, "not retrieved"):
            check_usage(usage)
        usage["lessons"][0].update(revision=1, effect="helped")
        with self.assertRaisesRegex(ValueError, "needs evidence"):
            check_usage(usage)

    def test_changed_receipt_or_wrong_stage_cannot_certify_usage(self):
        _, usage = self.packet()
        usage["stage"] = "inflation"
        with self.assertRaisesRegex(ValueError, "run and stage"):
            check_usage(usage)
        usage["stage"] = "base"
        path = usage["context_receipt"]["path"]
        write_json(path, {"tampered": True})
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            check_usage(usage)


if __name__ == "__main__":
    unittest.main()
