"""Producer isolation, stale completion and explicit resolution contracts."""
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from core.issues.coordinator import Coordinator
from core.issues.model import EntityReference, Issue
from core.issues.repository import IssueRepository
from core.issues.system import IssueSystem
from core.issues.resolution import Solver


def row(provider="a", revision="one"):
    return Issue(EntityReference("epoch", "scene", "root", "ARTIFACT", "mesh", 1),
                 "QUALITY", "Measured defect", provider=provider, stage="skin", artifact_revision=revision)


class IssueSystemTests(unittest.TestCase):
    def setUp(self):
        self.repo = IssueRepository()
        self.system = IssueSystem(self.repo, Coordinator(self.repo))

    def test_nested_evidence_is_an_immutable_snapshot(self):
        data = {"faces": [1, 2]}
        issue = replace(row(), evidence=(("details", data),))
        data["faces"].append(3)
        self.assertEqual(dict(issue.evidence)["details"]["faces"], (1, 2))
        with self.assertRaises(TypeError):
            dict(issue.evidence)["details"]["faces"] = ()

    def test_direct_and_listening_reports_share_store(self):
        a, b = row(), row("b")
        self.system.reporting.report(a)
        ticket = self.system.reporting.begin_check(b.entity.scope, b.provider)
        self.system.reporting.complete_check(ticket, [b])
        self.assertEqual(set(self.repo.records), {a.id, b.id})
        self.system.reporting.complete_check(ticket, [])
        self.assertEqual(set(self.repo.records), {a.id})

    def test_old_and_previous_epoch_results_cannot_clear_new_results(self):
        issue = row(); port = self.system.reporting
        old = port.begin_check(issue.entity.scope, issue.provider)
        current = port.begin_check(issue.entity.scope, issue.provider)
        port.complete_check(current, [issue])
        self.assertFalse(port.complete_check(old, []))
        self.system.reset()
        self.assertFalse(port.complete_check(current, []))
        self.assertIn(issue.id, self.repo.records)

    def test_failure_keeps_evidence_and_is_not_clean(self):
        issue = row(); self.system.reporting.report(issue)
        ticket = self.system.reporting.begin_check(issue.entity.scope, issue.provider)
        self.system.reporting.fail_check(ticket, "native unavailable")
        self.assertIn(issue.id, self.repo.records)
        value = self.system.presentation.serialize(issue)
        self.assertEqual(value["freshness"], "stale")
        self.assertFalse(self.repo.status()["complete"])

    def test_reporting_and_presentation_never_invoke_solver(self):
        calls = []; issue = row(); solve = self.system.resolution
        solve.register(Solver("fix", "Fix", ("QUALITY",), lambda *_: True, lambda *_: calls.append(1)))
        self.system.reporting.report(issue); self.system.presentation.rows()
        self.assertEqual(calls, [])
        solve.invoke(issue.id, "fix")
        self.assertEqual(calls, [1])
        self.system.reporting.invalidate(issue.entity.scope, issue.provider)
        with self.assertRaises(ValueError):
            solve.invoke(issue.id, "fix")

    def test_listener_jobs_are_isolated_by_provider(self):
        seen = []
        for provider in ("a", "b"):
            self.system.listening.schedule(provider, row().entity.scope,
                lambda token, p=provider: (seen.append(p) for _ in range(1)), delay=0)
        self.system.listening.coordinator.tick()
        self.assertCountEqual(seen, ["a", "b"])

    def test_fix_requires_fresh_verification_before_done(self):
        issue = row(); solve = self.system.resolution; port = self.system.reporting
        self.system.listening.register(SimpleNamespace(name="a", check_all=lambda _: port.begin_check(issue.entity.scope, "a")))
        solve.register(Solver("fix", "Fix", ("QUALITY",), lambda *_: True, lambda *_: None, poll=lambda *_: "DONE"))
        port.report(issue); solve.invoke(issue.id, "fix"); solve.tick()
        self.assertEqual(solve.running[issue.id]["state"], "VERIFYING")
        ticket = port.begin_check(issue.entity.scope, "a"); port.complete_check(ticket, [])
        self.assertFalse(solve.tick())
        self.assertEqual(solve.running[issue.id]["state"], "DONE")

    def test_failed_solver_poll_does_not_break_other_jobs(self):
        solve = self.system.resolution; issue = row()
        solve.register(Solver("fix", "Fix", ("QUALITY",), lambda *_: True, lambda *_: None,
                              poll=Mock(side_effect=RuntimeError("lost worker"))))
        self.system.reporting.report(issue); solve.invoke(issue.id, "fix")
        self.assertFalse(solve.tick())
        self.assertEqual(solve.running[issue.id]["state"], "FAILED")
        self.assertEqual(solve.running[issue.id]["error"], "lost worker")

    def test_revision_changes_reveal_previously_dismissed_issue(self):
        old, new = row(), row(revision="two")
        self.system.presentation.dismiss(old.id)
        self.assertNotEqual(old.id, new.id)
        self.assertNotIn(new.id, self.system.presentation.dismissed)

    def test_new_filters_and_provider_freshness(self):
        a, b = row(), row("b")
        self.system.reporting.report(a); self.system.reporting.report(b)
        self.system.reporting.invalidate(a.entity.scope, a.provider)
        total, rows = self.system.presentation.rows({"provider": "b", "stage": "skin"})
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["freshness"], "current")
