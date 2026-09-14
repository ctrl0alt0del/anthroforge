"""Production route-policy and native preparation regression tests."""

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np

from core.vcp.v2 import planner as p
from core.vcp.v2 import planner_preparation as prep
from core.vcp.v2 import planner_session as session_module
from core.vcp.v2.planner_search import RoadmapPolicy, RoadmapOutcome
from tests.roadmap_reference import ReferenceRoadmapPreparation
from tests.unit.test_fiber_v2_planner import _request, _anchors, _box


def _drain(iterator):
    while True:
        try: next(iterator)
        except StopIteration as stop: return stop.value


def _direct_graph(state, start, end):
    yield "DENSE", (start.point, end.point), ((1,), (0,))


def _fixture():
    return _request(_anchors(((-1., 0., 0.), (1., 0., 0.))), (_box(),))


def _forced_recovery(request=None, policy=None):
    with patch.object(session_module, "_ordinary_graphs", _direct_graph):
        return p.plan_reference_v43(request or _fixture(), policy=policy or RoadmapPolicy(True))


class RoadmapPreparationTests(unittest.TestCase):
    def check_graph(self, points, old, limit):
        graph = tuple(tuple(j for j in range(old) if j != i and (i+j) % 3) for i in range(old))
        self.assertEqual(p.append_access_neighbors(points, graph, limit), prep.native_neighbors(points, graph, limit))

    def test_random_neighbors(self):
        rng = np.random.default_rng(914)
        for count in (2, 3, 17, 65, 256, 843):
            for limit in (0, 1, 4, 48, count): self.check_graph(rng.normal(size=(count, 3)), max(2, count//3), limit)

    def test_ties_duplicates_and_scales(self):
        points = np.asarray([[x, y, z] for x in (-1., 0., 1.) for y in (-1., 0., 1.) for z in (-1., 0., 1.)])
        points = np.concatenate((points, points, np.zeros((9, 3))))
        for scale in (1e-9, 1., 1e8):
            for k in (1, 4, 12, 48): self.check_graph(points*scale, 10, k)

    def test_near_ties(self):
        points = np.random.default_rng(2914).normal(size=(128, 3))
        self.check_graph(np.concatenate((points, np.nextafter(points, np.inf), points)), 17, 48)

    def test_bad_native_arrays(self):
        for points in (np.zeros((3, 2)), np.full((3, 3), np.nan)):
            with self.assertRaises(ValueError): prep.native_neighbors(points, ((1,), (0,)))
        with self.assertRaises(ValueError): prep.native_neighbors(np.zeros((3, 3)), ((-1,), (0,)))

    def test_stable_dedup(self):
        original = np.asarray([[0., 0., 0.], [0., 0., 0.], [1., 2., 3.]])
        samples = np.asarray([[1, 2, 3], [3, 2, 1], [3, 2, 1], [1e-12, 0, 0]])
        np.testing.assert_array_equal(p.append_access_points(original, samples), prep.unique_points(original, samples))

    def test_probes(self):
        values = np.random.default_rng(59).normal(size=(100, 3)); values[2] = values[3]
        edges = np.asarray([(i, (i+1) % 100) for i in range(100)])
        owners = tuple(('A' if i % 2 else '', 'B' if i % 3 else '') for i in range(100))
        for span in (0., .005, 100.):
            a, rows = p._owner_chord_probes(values, edges, owners, span, .002, [True]*100)
            b, new_rows = prep.owner_probes(values, edges, owners, span, .002, [True]*100)
            self.assertEqual(rows, new_rows); np.testing.assert_allclose(a, b, rtol=0, atol=1e-14)

    def test_cache_keys(self):
        points = np.random.default_rng(6).normal(size=(32, 3)); pairs = [(i, i+1) for i in range(31)]
        owners, clear = [('A', '')]*31, [True]*31
        old, new = SimpleNamespace(edge_cache={}), SimpleNamespace(edge_cache={})
        p._store_edge_states(old, points, pairs, owners, clear); prep.store_edges(new, points, pairs, owners, clear)
        self.assertEqual(old.edge_cache, new.edge_cache)

    def test_asymmetric_anchor_links(self):
        graph = ((0, 2), (3,), (1, 3), (0, 1, 2)); pairs = prep.anchor_pairs(graph)
        self.assertEqual(pairs.tolist(), [[0, 2], [0, 3], [1, 2], [1, 3]])
        clear = [True, False, False, True]; blocked = {(0, 3), (1, 2)}
        expected = tuple(tuple(j for j in row if tuple(sorted((i, j))) not in blocked) for i, row in enumerate(graph))
        self.assertEqual(expected, prep.filtered_graph(graph, pairs, clear))


class RoadmapRecoveryTests(unittest.TestCase):
    def test_production_enables_conditional_recovery(self):
        with patch.object(session_module, "_ordinary_graphs", _direct_graph):
            result = p.plan_reference_v43(_fixture())
        self.assertTrue(result.succeeded)
        self.assertEqual(len(result.diagnostics.recoveries), 1)

    def test_recovers_one_failed_graph(self):
        result = _forced_recovery()
        self.assertTrue(result.succeeded, result.message)
        self.assertEqual(len(result.diagnostics.recoveries), 1)
        self.assertEqual(result.diagnostics.recoveries[0].trigger, RoadmapOutcome.GRAPH_DISCONNECTED)
        self.assertEqual(len(result.reference), 32)

    def test_reference_matches_native(self):
        old_graphs, new_graphs = [], []
        reference = RoadmapPolicy(True, ReferenceRoadmapPreparation(p), lambda *args: old_graphs.append(args))
        native = RoadmapPolicy(True, observe_graph=lambda *args: new_graphs.append(args))
        first, second = _forced_recovery(policy=reference), _forced_recovery(policy=native)
        np.testing.assert_array_equal(first.reference, second.reference)
        np.testing.assert_array_equal(old_graphs[0][1], new_graphs[0][1])
        self.assertEqual(old_graphs[0][2:], new_graphs[0][2:])

    def test_no_retry_after_handoff_failure(self):
        with patch.object(p, "_exact_handoff", return_value=None): result = _forced_recovery()
        self.assertEqual(result.failure_reason, "HANDOFF_COUNT_FAILED")
        self.assertEqual(len(result.diagnostics.recoveries), 1)

    def test_ordinary_handoff_failure_never_starts_recovery(self):
        request = _request(_anchors(((-1., 0., 0.), (1., 0., 0.))))
        with patch.object(p, '_exact_handoff', return_value=None): result = p.plan_reference_v43(request)
        self.assertEqual(result.failure_reason, 'HANDOFF_COUNT_FAILED')
        self.assertEqual(result.diagnostics.recoveries, ())

    def test_no_retry_after_final_validation_failure(self):
        with patch.object(p, "validate_static_clearance", return_value=SimpleNamespace(valid=False)):
            result = _forced_recovery()
        self.assertEqual(result.failure_reason, "HANDOFF_VALIDATION_FAILED")
        self.assertEqual(len(result.diagnostics.recoveries), 1)

    def test_disabled_policy_keeps_old_failure(self):
        result = _forced_recovery(policy=RoadmapPolicy(False))
        self.assertFalse(result.succeeded); self.assertFalse(result.diagnostics.recoveries)
        self.assertEqual(result.failure_reason, "GRAPH_DISCONNECTED")

    def test_direct_bypasses_preparation(self):
        request = _request(_anchors(((-1., 0., 0.), (1., 0., 0.))))
        with patch.object(prep, "shell_samples", side_effect=AssertionError("expanded")):
            result = p.plan_reference_v43(request, policy=RoadmapPolicy(True))
        self.assertTrue(result.succeeded); self.assertEqual(result.diagnostics.recoveries, ())

    def test_invalid_anchor_does_not_retry(self):
        request = _request(_anchors(((0., 0., 0.), (1., 0., 0.))), (_box(),))
        result = p.plan_reference_v43(request, policy=RoadmapPolicy(True))
        self.assertEqual(result.failure_reason, "INVALID_ATTACHMENT")
        self.assertEqual(result.diagnostics.attempts, ())

    def test_backend_failure_does_not_retry(self):
        with patch.object(p, "collision_backend_status", return_value=SimpleNamespace(available=False)):
            result = p.plan_reference_v43(_fixture(), policy=RoadmapPolicy(True))
        self.assertEqual(result.failure_reason, "BACKEND_UNAVAILABLE")
        self.assertFalse(result.diagnostics.attempts)

    def test_cancellation_releases_capture(self):
        session = p.begin_plan_reference_v43(_fixture(), policy=RoadmapPolicy(True))
        session.step(); self.assertIsNotNone(session.state)
        session.cancel(); session.step()
        self.assertEqual(session.result.failure_reason, "CANCELLED")
        self.assertIsNone(session.state); self.assertIsNone(session.iterator)

    def test_supersede_releases_capture(self):
        session = p.begin_plan_reference_v43(_fixture()); session.step(); session.cancel(superseded=True)
        self.assertEqual(session.result.failure_reason, "SUPERSEDED")

    def test_interleaved_same_ids_are_isolated(self):
        request = _fixture(); a = p.begin_plan_reference_v43(request, policy=RoadmapPolicy(True))
        b = p.begin_plan_reference_v43(replace(request, root_id="other"), policy=RoadmapPolicy(False))
        with patch.object(session_module, "_ordinary_graphs", _direct_graph):
            while not (a.done and b.done): a.step(); b.step()
        self.assertTrue(a.result.succeeded); self.assertFalse(b.result.succeeded)
        self.assertEqual(b.result.diagnostics.recoveries, ())

    def test_sync_and_resumable_parity(self):
        policy = RoadmapPolicy(True); request = _fixture()
        sync = p.plan_reference_v43(request, policy=policy)
        session = p.begin_plan_reference_v43(request, policy=policy)
        while not session.done: session.step()
        self.assertEqual(sync.reference, session.result.reference)
        self.assertEqual(sync.termination, session.result.termination)

    def test_v2_core_yields_and_cancels_planning(self):
        from core.vcp.v2.contact_core import begin_contact_core
        session = begin_contact_core(_fixture())
        while session.phase != 'PLAN': session.step()
        session.step(); planner = session.planner_session
        self.assertIsNotNone(planner); self.assertFalse(planner.done)
        session.cancel()
        self.assertTrue(planner.done); self.assertIsNone(planner.state)

    def test_closing_loop_span_recovers_without_replanning_other_spans(self):
        request = _request(_anchors(((-1., 0., 0.), (0., 1., 0.), (1., 0., 0.))),
                           (_box(),), topology=p.V2Topology.CYCLIC)
        result = _forced_recovery(request)
        self.assertTrue(result.succeeded, result.message)
        self.assertEqual([r.span for r in result.diagnostics.recoveries], [2])
        self.assertEqual(len(result.reference), request.settings.node_count)

    def test_search_cap_is_not_reported_as_disconnection(self):
        result = SimpleNamespace(status=2, searches=512, expansions=1, validated=0, rejected=1,
            candidates=1, tested=1, search_ms=1., collision_ms=1.)
        state = p._v43_state(_fixture(), None, 2.5)
        from core.vcp.v2.planner_search import RoadmapSearchContext
        state.search_context = RoadmapSearchContext()
        with patch.object(state.native_world, 'lazy_path', return_value=((), result)):
            session_module._search(state, 'DENSE', ((-1., 0., 0.), (1., 0., 0.)), ((1,), (0,)),
                                   *state.request.anchors)
        self.assertEqual(state.search_context.outcome, RoadmapOutcome.SEARCH_BUDGET_EXHAUSTED)

    def test_no_experimental_imports(self):
        import ast
        from pathlib import Path
        for name in ('planner_session.py', 'planner_preparation.py', 'planner_search.py'):
            tree = ast.parse((Path(p.__file__).parent/name).read_text())
            modules = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            self.assertFalse(any('experiment' in module or 'artifacts' in module for module in modules))


if __name__ == '__main__': unittest.main()
