"""Pure warning storage, identity, scheduling and protocol contracts."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from core.warnings.model import EntityReference, PinReference, Warning
from core.warnings.repository import WarningRepository
from core.warnings.coordinator import Coordinator
from core.warnings import session
from core.warnings.query import WarningQuery
from core.authoring import schema, validation
from core.authoring.reports import response


def warning(native="F1", blocker="S1", scene="scene", root="root"):
    ref = EntityReference("epoch", scene, root, "FIBER", native, 1, native)
    pin = PinReference("TOUCH", 1, 1, "fingerprint")
    return Warning(ref, pin, "FIBER_INVALID_HARD_ANCHOR", "Blocked", "Move pin",
                   (("blocker_id", blocker),))


def request(version="0.4.0", **params):
    return dict(version=version, message_type="request", request_id="warning_query",
                op="warnings.list", params=dict(scene_id="scene", **params))


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.repo = WarningRepository()

    def test_semantic_dedup_is_not_message_text(self):
        row = warning()
        self.repo.replace(row.entity.scope, [row, replace(row, summary="Updated wording")])
        self.assertEqual(len(self.repo.records), 1)
        self.assertEqual(self.repo.records[row.id].summary, "Updated wording")

    def test_atomic_replacement_and_empty_success_remove_only_checked_scope(self):
        a, b = warning(), warning("F2")
        self.repo.replace(a.entity.scope, [a]); self.repo.replace(b.entity.scope, [b])
        seen = []; self.repo.subscribe(lambda repo: seen.append(len(repo.records)))
        self.repo.replace(a.entity.scope, [])
        self.assertEqual(seen, [1]); self.assertIn(b.id, self.repo.records)
        self.assertEqual(self.repo.states[a.entity.scope]["status"], "COMPLETE")

    def test_wrong_scope_reconciliation_is_rejected_atomically(self):
        a, b = warning(), warning("F2")
        self.repo.replace(a.entity.scope, [a])
        with self.assertRaises(ValueError):
            self.repo.replace(a.entity.scope, [b])
        self.assertEqual(tuple(self.repo.records), (a.id,))

    def test_multiple_roots_scenes_and_duplicate_ids_are_distinct(self):
        rows = [warning(), warning(root="other"), warning(scene="other")]
        for row in rows:
            self.repo.replace(row.entity.scope, [row])
        self.assertEqual(self.repo.query(dict(entity="F1"))[0], 3)
        self.assertEqual(self.repo.query(dict(scene="scene", root="root"))[1], (rows[0],))

    def test_order_pagination_and_removal_indexes(self):
        rows = [warning(str(index)) for index in range(230)]
        for row in reversed(rows):
            self.repo.replace(row.entity.scope, [row])
        total, page = self.repo.query(limit=1000)
        self.assertEqual((total, len(page)), (230, 200))
        self.assertEqual(self.repo.query(offset=1, limit=1)[1], page[1:2])
        self.repo.remove(page[0].entity.scope)
        self.assertEqual(self.repo.query(dict(entity=page[0].entity.native_id))[0], 0)

    def test_unscanned_pending_failed_cancelled_never_mean_clean(self):
        self.assertFalse(self.repo.status()["complete"])
        self.repo.discovery = "COMPLETE"
        for state in ("UNSCANNED", "PENDING", "CHECKING", "FAILED", "CANCELLED"):
            self.repo.state(warning().entity.scope, state)
            self.assertFalse(self.repo.status()["complete"], state)
        self.repo.replace(warning().entity.scope, [])
        self.assertTrue(self.repo.status()["complete"])

    def test_failure_keeps_findings_and_labels_them_stale(self):
        row = warning(); self.repo.replace(row.entity.scope, [row])
        self.repo.state(row.entity.scope, "FAILED", error="Backend unavailable")
        self.assertIn(row.id, self.repo.records)
        wire = row.serialize("FAILED", self.repo.revision)
        self.assertEqual(wire["freshness"], "stale")

    def test_upsert_and_provider_scoped_replacement_preserve_other_findings(self):
        first, second = warning(), replace(warning(), provider="other.v1", code="OTHER")
        self.repo.upsert(first); self.repo.upsert(second)
        self.repo.replace(first.entity.scope, [], provider=first.provider)
        self.assertEqual(tuple(self.repo.records), (second.id,))
        self.repo.upsert(replace(second, summary="Changed"))
        self.assertEqual(len(self.repo.records), 1)

    def test_subscriber_failure_does_not_corrupt_authoritative_result(self):
        def fail(_repo):
            raise ValueError("UI unavailable")
        self.repo.subscribe(fail)
        row = warning()
        with self.assertLogs("core.warnings.repository", level="ERROR"):
            self.repo.replace(row.entity.scope, [row])
        self.assertIn(row.id, self.repo.records)

    def test_other_provider_completion_cannot_clear_pending_primary_check(self):
        first = warning(); other = replace(first, provider="other.v1", code="OTHER")
        self.repo.replace(first.entity.scope, [first], metadata="anchor metadata")
        self.repo.state(first.entity.scope, "PENDING")
        self.repo.upsert(other)
        self.assertEqual(self.repo.states[first.entity.scope]["status"], "PENDING")
        self.assertEqual(self.repo.metadata[first.entity.scope, first.provider], "anchor metadata")


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.repo = WarningRepository(); self.scheduler = Coordinator(self.repo)

    def test_work_is_bounded_and_resumable(self):
        seen = []
        self.scheduler.enqueue("job", lambda token: (seen.append(i) for i in range(100)))
        self.assertTrue(self.scheduler.tick(max_steps=3))
        self.assertEqual(seen, [0, 1, 2])
        while self.scheduler.tick(max_steps=3):
            pass
        self.assertEqual(len(seen), 100)

    def test_incremental_supersedes_older_global_work(self):
        seen = []
        old = self.scheduler.enqueue("root", lambda token: (seen.append("old") for _ in range(3)))
        self.scheduler.tick(max_steps=1)
        new = self.scheduler.enqueue("root", lambda token: (seen.append("new") for _ in range(2)))
        self.assertFalse(self.scheduler.current("root", old))
        self.scheduler.tick(max_steps=10)
        self.assertEqual(seen, ["old", "new", "new"])
        self.assertTrue(self.scheduler.current("root", new))

    def test_fake_clock_budget_stops_between_units(self):
        now = iter([0, 0.009, 0.01])
        scheduler = Coordinator(self.repo, clock=lambda: next(now))
        seen = []
        scheduler.enqueue("root", lambda token: (seen.append(i) for i in range(50)))
        scheduler.tick(budget_ms=8)
        self.assertEqual(seen, [0])
        self.assertGreaterEqual(scheduler.metrics["duration_ms"], 8)

    def test_cancel_retires_token_and_nonclean_state(self):
        row = warning(); self.repo.state(row.entity.scope, "CHECKING")
        token = self.scheduler.enqueue("root", lambda generation: iter([1, 2]))
        self.scheduler.cancel_all()
        self.assertFalse(self.scheduler.current("root", token))
        self.assertEqual(self.repo.states[row.entity.scope]["status"], "CANCELLED")


class IdentityAndProtocolTests(unittest.TestCase):
    def setUp(self):
        session.reset()

    def test_identical_recreation_at_reused_pointer_retires_incarnation(self):
        entity = SimpleNamespace(id="F1", name="Fiber", as_pointer=lambda: 42)
        scene, root = SimpleNamespace(session_uid=1), SimpleNamespace(session_uid=2)
        before = session.entity_reference(scene, root, entity)
        session.retire(root, {"F1"})
        recreated = SimpleNamespace(**vars(entity))
        self.assertNotEqual(before.scope, session.entity_reference(scene, root, recreated).scope)

    def test_rename_preserves_identity_and_pin_reorder_changes_revision(self):
        entity, scene, root = SimpleNamespace(id="F1", name="Old"), object(), object()
        ref = session.entity_reference(scene, root, entity)
        first = session.attachment_identity(ref, ["A", "B"])
        entity.name = "New"
        self.assertEqual(ref.scope, session.entity_reference(scene, root, entity).scope)
        self.assertNotEqual(first, session.attachment_identity(ref, ["B", "A"]))

    def test_file_epoch_changes_even_if_blender_session_ids_are_reused(self):
        scene, root, fiber = object(), object(), SimpleNamespace(id="F1")
        before = session.entity_reference(scene, root, fiber)
        session.reset()
        self.assertNotEqual(before.scope, session.entity_reference(scene, root, fiber).scope)

    def test_warning_request_and_response_schemas_all_versions(self):
        for version in ("0.2.0", "0.3.0", "0.4.0"):
            value = request(version, scene="1", root="2", entity="F1", limit=20)
            validation.request(value)
            result = dict(response(value), warnings=WarningQuery().list(value["params"]))
            schema.validate(result, "protocol")

    def test_query_has_live_revision_and_bounded_results(self):
        first = WarningQuery().list()
        row = warning(); session.REPOSITORY.replace(row.entity.scope, [row])
        second = WarningQuery().list(dict(limit=1))
        self.assertEqual(second["total"], 1)
        self.assertNotEqual(first["check_token"], second["check_token"])
        self.assertEqual(second["records"][0]["pin"]["role"], "TOUCH")

    def test_feedback_decorates_copy_without_poisoning_cached_response(self):
        cached = dict(status="success", diagnostics=[])
        first = WarningQuery().feedback(dict(op="patch"), cached)
        row = warning(); session.REPOSITORY.replace(row.entity.scope, [row])
        second = WarningQuery().feedback(dict(op="patch"), cached, replayed=True)
        self.assertNotIn("warnings", cached)
        self.assertNotEqual(first["warnings"]["check_token"], second["warnings"]["check_token"])


if __name__ == "__main__":
    unittest.main()
