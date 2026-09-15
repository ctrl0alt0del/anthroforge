"""Accepted exit sampling/tree parity, safety, isolation and coordinator gates."""

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from core.vcp.v2 import planner as p, planner_session as ps, planner_preparation as prep
from core.vcp.v2.planner_pin_tree import ExitTree, PinExitPolicy, goal_forest, grow_pair
from core.vcp.v2.planner_pin_graph import augmented_neighbors, component, PinExitGraph
from core.vcp.v2.planner_pin_recovery import eligible, sampling_scale
from core.vcp.v2.planner_search import RoadmapPolicy, RoadmapSearchContext, RoadmapOutcome, RoadmapAttempt
from core.vcp.v2.collision_native import native_roadmap_nearest_batch
from tests.unit.test_fiber_v2_planner import _request, _anchors, _box


def box_clear(points, pairs, owners):
    if not len(pairs): return ()
    segments = np.asarray(points)[np.asarray(pairs)]; start = segments[:, 0]; delta = segments[:, 1]-start
    low, high = np.array((.035, -1., -1.)), np.array((.085, .10, 1.))
    parallel = np.abs(delta) < 1e-15; divisor = np.where(parallel, 1., delta)
    a, b = (low-start)/divisor, (high-start)/divisor
    enter = np.where(parallel, -np.inf, np.minimum(a, b)).max(axis=1)
    leave = np.where(parallel, np.inf, np.maximum(a, b)).min(axis=1)
    outside = np.any(parallel & ((start < low) | (start > high)), axis=1)
    return outside | (np.maximum(enter, 0.) > np.minimum(leave, 1.))


def drain(iterator):
    while True:
        try: next(iterator)
        except StopIteration as stop: return stop.value


def validator(check, calls=None):
    def validate(points, pairs, owners):
        if calls is not None: calls.extend((np.asarray(points)[i].copy(), a) for (i, j), (a, b) in zip(pairs, owners) if a)
        result = np.asarray(check(points, pairs, owners), dtype=bool)
        yield 'COLLISION'
        return result
    return validate


def tree_fixture(check=box_clear, calls=None):
    return ExitTree((0., 0., 0.), 'owner', ((.12, 0., 0.),), validator(check, calls), .01)


def solve_tree(tree, policy):
    added = yield from tree.initial(policy)
    found = yield from tree.connect(added)
    if found: return found
    forest = goal_forest(tree)
    for batch in range(policy.growth_batches):
        found = yield from grow_pair(tree, forest, batch)
        if found: return found
    return None


class PinExitTreeTests(unittest.TestCase):
    def test_accepted_reference_bitwise_parity(self):
        reference = json.loads((Path(__file__).parent/'fixtures/pin_exit_tree_reference.json').read_text())
        tree = tree_fixture(); result = drain(solve_tree(tree, PinExitPolicy(directions=128, growth_batches=64)))
        np.testing.assert_array_equal(result[0], reference['path'])
        self.assertEqual(result[1], reference['goal_index'])
        self.assertEqual(len(tree.points), reference['node_count'])
        self.assertEqual(sha256(np.asarray(tree.points, dtype='<f8').tobytes()).hexdigest(), reference['points_sha256'])
        self.assertEqual(sha256(np.asarray(tree.parents, dtype='<i8').tobytes()).hexdigest(), reference['parents_sha256'])

    def test_bent_connection_and_every_edge_clear(self):
        tree = tree_fixture(); found = drain(solve_tree(tree, PinExitPolicy(directions=128, growth_batches=64)))
        self.assertIsNotNone(found)
        self.assertFalse(box_clear([[0,0,0], [.12,0,0]], [(0,1)], ())[0])
        points = np.asarray((*found[0], (.12,0,0))); edges = [(i,i+1) for i in range(len(points)-1)]
        self.assertTrue(all(box_clear(points, edges, ())))
        self.assertTrue(all(box_clear(tree.points, [(j,i) for i,j in enumerate(tree.parents) if j >= 0], ())))

    def test_owner_only_at_authored_pin(self):
        calls = []; tree = tree_fixture(calls=calls)
        drain(solve_tree(tree, PinExitPolicy(directions=128, growth_batches=64)))
        self.assertTrue(calls)
        for point, owner in calls: np.testing.assert_array_equal(point, (0,0,0))

    def test_interleaved_generators_deterministic(self):
        policy = PinExitPolicy(directions=128, growth_batches=64); a, b = tree_fixture(), tree_fixture()
        one, two = solve_tree(a, policy), solve_tree(b, policy); results = []
        pending = [one, two]
        while pending:
            for item in pending[:]:
                try: next(item)
                except StopIteration as stop: results.append(stop.value); pending.remove(item)
        self.assertEqual(results[0], results[1]); np.testing.assert_array_equal(a.points, b.points)

    def test_no_exits_bounded(self):
        tree = tree_fixture(lambda p,e,o: [False]*len(e))
        self.assertIsNone(drain(solve_tree(tree, PinExitPolicy(directions=128, growth_batches=4))))
        self.assertEqual(tree.stats['initial_exits'], 0); self.assertEqual(tree.stats['batches'], 4)
        self.assertLessEqual(tree.stats['proposals'], 384+128)
        self.assertEqual(tree.stats['targets'], 128)

    def test_empty_goal_sampling_still_runs_without_connect(self):
        tree = tree_fixture(); tree.goals = np.empty((0,3))
        exits = drain(tree.initial(PinExitPolicy(directions=128)))
        self.assertIsNone(drain(tree.connect(exits)))


class PinExitGraphTests(unittest.TestCase):
    def test_selected_owner_guard_matches_full_guard_exactly(self):
        request = _request(_anchors(((-1,0,0),(1,0,0))), (_box(),))
        state = p._v43_state(request, None, 2.5); graph = PinExitGraph(state, *request.anchors)
        points = np.random.default_rng(17).uniform(-.8,.8,(64,3)); pairs = [(i,i+1) for i in range(63)]
        owner = request.colliders[0].owner_id
        roles = tuple((owner if i%5==0 else '', owner if i%7==0 else '') for i in range(63))
        expected = p.validate_native_owner_chords(request, state.native_world, points, pairs, roles,
                                                  p._state_contact_span(state), p._radius(state)-p._slack(state)).clear
        self.assertEqual(tuple(drain(graph.validate(points, pairs, roles))), expected)

    def test_batched_native_matches_existing_preparation(self):
        rng = np.random.default_rng(41)
        for size in (2, 3, 32, 129, 1024):
            points = rng.normal(size=(size,3)); points[:min(3,size)] = 0
            original = ((1,), (0,))
            for k in (0, 1, 48):
                self.assertEqual(drain(augmented_neighbors(points, original, k)), prep.native_neighbors(points, original, k))

    def test_asymmetric_links_duplicates_ties_preserved(self):
        points = np.asarray([[i%3, i%2, 0.] for i in range(40)])
        original = ((2,), (), (1, 2))
        self.assertEqual(drain(augmented_neighbors(points, original)), prep.native_neighbors(points, original))

    def test_native_rejects_bad_batch(self):
        for first, count, k in ((-1,1,48),(0,65,48),(2,2,48),(0,1,-1)):
            with self.assertRaises(ValueError): native_roadmap_nearest_batch(np.zeros((3,3)), first, count, k)
        with self.assertRaises(ValueError): native_roadmap_nearest_batch(np.full((3,3), np.nan), 0, 1)

    def test_component_preserves_bfs_insertion_order(self):
        self.assertEqual(list(drain(component(((2,1),(3,),(3,),()), 0))), [0,2,1,3])

    def test_only_unchanged_indexed_edges_reused(self):
        state = SimpleNamespace(); start = SimpleNamespace(owner_id='A'); end = SimpleNamespace(owner_id='B')
        graph = PinExitGraph(state, start, end); calls = []
        def validate(points, pairs, owners):
            calls.extend(zip(pairs, owners)); yield 'CHECK'
            return np.ones(len(pairs), dtype=bool)
        graph.validate = validate
        first = drain(graph.checked(np.zeros((3,3)), ((1,), (0,2), (1,))))
        second = drain(graph.checked(np.zeros((4,3)), ((1,), (0,2), (1,3), (2,))))
        self.assertEqual(len(calls), 3); self.assertEqual(graph.cache_hits, 2)
        self.assertEqual(calls[0][1], ('A','B')); self.assertEqual(first[0], second[0])


def eligibility_fixture(reason=RoadmapOutcome.GRAPH_DISCONNECTED):
    context = RoadmapSearchContext(); context.remember(((0,0,0),(1,0,0)), ((),()))
    context.attempts.append(RoadmapAttempt(0, 'EXPANDED', reason, 2, 0))
    return SimpleNamespace(policy=RoadmapPolicy(expanded=True, pin_recovery=True),
                           state=SimpleNamespace(search_context=context))


class PinExitPolicyTests(unittest.TestCase):
    def test_closing_span_keeps_its_own_recovery_scope(self):
        context = RoadmapSearchContext(); anchors = _anchors(((0,0,0),(1,0,0),(0,1,0)))
        session = SimpleNamespace(state=SimpleNamespace(request=SimpleNamespace(anchors=anchors), search_context=context))
        calls = []
        def pair(value, start, end):
            calls.append((context.span, start, end)); yield 'SPAN'
            return (start.point, end.point)
        with patch.object(p, '_cyclic', return_value=True), patch.object(ps, '_pair_steps', side_effect=pair):
            result = drain(ps._span_steps(session))
        self.assertEqual(len(result), 3)
        self.assertEqual(calls[-1], (2, anchors[-1], anchors[0]))

    def test_production_has_no_experimental_imports(self):
        import ast
        from pathlib import Path
        paths = list(Path(p.__file__).parent.glob('planner_pin*.py'))
        paths += list(Path(p.__file__).parents[1].glob('fiber_pin_snap*.py'))
        for path in paths:
            tree = ast.parse(path.read_text())
            modules = [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            modules += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
            self.assertFalse(any(any(word in name for word in ('experiment', 'artifacts', 'tools')) for name in modules))

    def test_eligibility_excludes_handoff_and_runtime_failures(self):
        allowed = {'GRAPH_DISCONNECTED','SEARCH_BUDGET_EXHAUSTED','CORRIDOR_VALIDATION_FAILED'}
        for reason in RoadmapOutcome: self.assertEqual(eligible(eligibility_fixture(reason)), reason.value in allowed)

    def test_one_recovery_per_span(self):
        session = eligibility_fixture(); context = session.state.search_context
        context.pin_recoveries.append(SimpleNamespace(span=0)); self.assertFalse(eligible(session))
        context.span = 1; self.assertTrue(eligible(session))
        context.release(); self.assertFalse(eligible(session))

    def test_zero_radius_uses_sampling_floor_only(self):
        request = _request(_anchors(((0,0,0),(1,0,0))))
        request = replace(request, collision_policy=replace(request.collision_policy, collision_radius=0))
        scale = sampling_scale(SimpleNamespace(request=request))
        self.assertGreater(scale, 0); self.assertEqual(request.collision_policy.collision_radius, 0)

    def test_success_never_starts_recovery(self):
        from core.vcp.v2 import planner_pin_recovery as recovery
        with patch.object(recovery, 'recover_steps', side_effect=AssertionError('unexpected recovery')):
            result = p.plan_reference_v43(_request(_anchors(((0,0,0),(1,0,0)))),
                                          policy=RoadmapPolicy(expanded=True, pin_recovery=True))
        self.assertTrue(result.succeeded); self.assertEqual(result.diagnostics.pin_recoveries, ())

    def test_invalid_attachment_never_starts_recovery(self):
        from core.vcp.v2 import planner_pin_recovery as recovery
        with patch.object(recovery, 'recover_steps', side_effect=AssertionError('unexpected recovery')):
            result = p.plan_reference_v43(_request(_anchors(((0,0,0),(1,0,0))), (_box(),)),
                                          policy=RoadmapPolicy(expanded=True, pin_recovery=True))
        self.assertFalse(result.succeeded); self.assertEqual(result.failure_reason, 'INVALID_ATTACHMENT')

    def test_cancel_closes_active_recovery(self):
        from core.vcp.v2 import planner_pin_recovery as recovery
        session = eligibility_fixture(); iterator = recovery.recover_steps(session, SimpleNamespace(), SimpleNamespace())
        closed = []
        def run(instance):
            instance.graph.edge_results[(0,1)] = True
            try: yield 'WAIT'
            finally: closed.append(instance)
        with patch.object(recovery.PinExitRecovery, 'run', run):
            self.assertEqual(next(iterator), 'WAIT'); iterator.close()
        self.assertFalse(closed[0].graph.edge_results); self.assertFalse(closed[0].trees)


if __name__ == '__main__': unittest.main()
