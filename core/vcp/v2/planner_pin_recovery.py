"""Conditional exit sampling, then bounded bent connections into the existing graph."""

from dataclasses import dataclass, field
import numpy as np
from . import planner as p, planner_preparation as prep
from .planner_pin_graph import PinExitGraph, component, join_route, augmented_neighbors, checked_anchors
from .planner_pin_tree import PIN_EXIT_POLICY, ExitTree, goal_forest, grow_pair
from .planner_search import RoadmapAttempt, RoadmapOutcome


ELIGIBLE_FAILURES = frozenset((RoadmapOutcome.GRAPH_DISCONNECTED,
    RoadmapOutcome.SEARCH_BUDGET_EXHAUSTED, RoadmapOutcome.CORRIDOR_VALIDATION_FAILED))


@dataclass(frozen=True)
class PinExitRecoveryResult:
    span: int
    trigger: RoadmapOutcome
    outcome: RoadmapOutcome
    stage: str
    initial_exits: tuple
    proposals: int
    growth_batches: int
    collision_queries: int
    graph_cache_hits: int
    side_outcomes: tuple
    search_seed: int = 914
    growth_targets: int = 0
    sampling_outcome: str = ''


@dataclass
class PinExitRecovery:
    state: object
    start: object
    end: object
    policy: object = PIN_EXIT_POLICY
    trees: list = field(default_factory=list)
    forests: list = field(default_factory=list)
    sides: list = field(default_factory=list)
    stage: str = 'SAMPLING'
    outcome: object = RoadmapOutcome.PIN_EXIT_SAMPLES_EXHAUSTED
    sampling_outcome: str = ''

    def __post_init__(self):
        self.context = self.state.search_context; self.trigger = self.context.outcome
        self.graph = PinExitGraph(self.state, self.start, self.end, self.policy)
        self.points, self.neighbors = self.context.last_graph

    def groups(self):
        checked = yield from self.graph.checked(self.points, self.neighbors)
        first = yield from component(checked, 0)
        second = yield from component(checked, 1)
        return first, second

    def sample(self, groups):
        route = None
        for side, anchor in enumerate((self.start, self.end)):
            goals = tuple(i for i in groups[1-side] if i >= 2)
            tree = ExitTree(anchor.point, anchor.owner_id, np.asarray(self.points)[list(goals)],
                            self.graph.validate, sampling_scale(self.state), self.policy.seed)
            self.trees.append(tree); added = yield from tree.initial(self.policy)
            found = yield from tree.connect(added)
            joined = (yield from self.join(groups, goals, side, found)) if found else None
            if joined is not None and route is None: route = joined
        return route

    def join(self, groups, goals, side, found):
        return (yield from join_route(self.state, self.points, groups, goals, side, found, self.start, self.end))

    def augment(self):
        from .planner_session import _search, _check_route
        samples = tuple(point for tree in self.trees for point in tree.points[1:])
        self.points = prep.unique_points(self.points, samples)
        yield 'PIN_EXIT_DEDUP'
        graph = yield from augmented_neighbors(self.points, self.neighbors, 48)
        self.neighbors = yield from checked_anchors(self.state, self.points, graph, self.start, self.end)
        route = _search(self.state, 'PIN_EXIT_SAMPLING_GRAPH', self.points, self.neighbors, self.start, self.end)
        yield 'PIN_EXIT_GRAPH_SEARCH'
        if route is not None: route = _check_route(self.state, route, self.start, self.end, True)
        yield 'PIN_EXIT_CORRIDOR_VALIDATE'
        return route

    def grow(self, groups, side):
        goals = tuple(i for i in groups[1-side] if i >= 2)
        if not goals:
            self.sides.append((side, RoadmapOutcome.NO_OPPOSITE_COMPONENT)); return None
        tree = self.trees[side]; tree.goals = np.asarray(self.points)[list(goals)]
        forest = goal_forest(tree); self.forests.append(forest); found = None
        for batch in range(self.policy.growth_batches):
            found = yield from grow_pair(tree, forest, batch)
            if found is not None: break
        route = (yield from self.join(groups, goals, side, found)) if found else None
        reason = RoadmapOutcome.CORRIDOR_VALIDATION_FAILED if found else RoadmapOutcome.LOCAL_CONNECTION_BUDGET_EXHAUSTED
        self.sides.append((side, RoadmapOutcome.SUCCESS if route is not None else reason))
        return route

    def search(self):
        self.stage = 'LOCAL_SEARCH'; groups = yield from self.groups()
        for side in sorted((0, 1), key=lambda i: (len(groups[i]), i)):
            route = yield from self.grow(groups, side)
            if route is not None: return route
        self.outcome = next((reason for _, reason in self.sides if reason != RoadmapOutcome.NO_OPPOSITE_COMPONENT),
                            RoadmapOutcome.NO_OPPOSITE_COMPONENT)
        return None

    def run(self):
        groups = yield from self.groups(); route = yield from self.sample(groups)
        if route is None: route = yield from self.augment()
        self.sampling_outcome = ('SUCCESS' if route is not None else
            ('NO_SAMPLED_EXIT' if not any(t.stats['initial_exits'] for t in self.trees) else 'NO_SAMPLED_CONNECTION'))
        if route is None: route = yield from self.search()
        if route is not None: self.outcome = RoadmapOutcome.SUCCESS
        self.record(route)
        return route

    def record(self, route):
        stats = [tree.stats for tree in (*self.trees, *self.forests)]
        result = PinExitRecoveryResult(self.context.span, self.trigger, self.outcome, self.stage,
            tuple(t.stats['initial_exits'] for t in self.trees), sum(s['proposals'] for s in stats),
            sum(s['batches'] for s in stats), self.graph.queries, self.graph.cache_hits, tuple(self.sides),
            self.policy.seed, sum(s['targets'] for s in stats), self.sampling_outcome)
        self.context.pin_recoveries.append(result)
        self.context.attempts.append(RoadmapAttempt(self.context.span, 'PIN_EXIT_'+self.stage,
            self.outcome, len(self.points), sum(map(len, self.neighbors)), tested_pairs=self.graph.queries))
        self.state.candidate_nodes = max(self.state.candidate_nodes, len(self.points))


def sampling_scale(state):
    tolerance = state.request.tolerances
    return max(p._radius(state), 4*tolerance.clearance_slack, tolerance.numeric_floor, 1e-7)


def eligible(session):
    context = session.state.search_context
    return (session.policy.pin_recovery and context.last_graph is not None and context.outcome in ELIGIBLE_FAILURES
            and not any(row.span == context.span for row in context.pin_recoveries))


def recover_steps(session, start, end):
    if not eligible(session): return None
    recovery = PinExitRecovery(session.state, start, end)
    try: return (yield from recovery.run())
    finally:
        recovery.graph.edge_results.clear()
        recovery.trees.clear(); recovery.forests.clear()
