"""Bounded, deterministic local trees; only copied arrays and injected validation.

Accepted seed-914 connector, inspired by dynamic-domain RRT (Yershova et al.,
2005). This finite search makes no completeness or shortest-path guarantee.
"""

from dataclasses import dataclass, field
import numpy as np


@dataclass(frozen=True)
class PinExitPolicy:
    seed: int = 914
    directions: int = 2048
    radii: tuple = (2., 2.5, 4.)
    growth_batches: int = 256
    query_batch: int = 256


PIN_EXIT_POLICY = PinExitPolicy()


def sphere_directions(count):
    index = np.arange(count); z = 1-2*(index+.5)/count
    angle = index*np.pi*(3-np.sqrt(5)); radial = np.sqrt(1-z*z)
    return np.column_stack((radial*np.cos(angle), radial*np.sin(angle), z))


@dataclass
class ExitTree:
    point: object
    owner: str
    goals: object
    validate: object
    scale: float
    seed: int = 914
    points: list = field(default_factory=list)
    parents: list = field(default_factory=list)
    domains: list = field(default_factory=list)
    seen: set = field(default_factory=set)
    stats: dict = field(default_factory=dict)

    def __post_init__(self):
        self.point = np.asarray(self.point, dtype=np.float64)
        self.points = [self.point]; self.parents = [-1]; self.domains = [np.inf]
        self.goals = np.asarray(self.goals, dtype=np.float64).reshape(-1, 3)
        self.rng = np.random.default_rng(self.seed)
        self.seen = {tuple(np.round(self.point, 10))}
        self.stats = dict(proposals=0, targets=0, accepted=0, queries=0, initial_exits=0, batches=0)

    def check(self, values, pairs, owners):
        self.stats['queries'] += len(pairs)
        return (yield from self.validate(values, pairs, owners))

    def initial(self, policy=PIN_EXIT_POLICY):
        directions = sphere_directions(policy.directions)
        candidates = np.vstack([self.point+directions*self.scale*f for f in policy.radii])
        yield 'PIN_EXIT_GENERATE'
        added = yield from self.accept(np.zeros(len(candidates), dtype=int), candidates)
        self.stats['initial_exits'] = len(added)
        return added

    def accept(self, parents, candidates):
        if not len(candidates): return []
        self.stats['proposals'] += len(candidates); values = np.vstack((self.points, candidates))
        indices = np.arange(len(self.points), len(values)); pairs = np.column_stack((indices, indices))
        free = yield from self.check(values, pairs, (('', ''),)*len(indices))
        pairs = np.column_stack((parents[free], indices[free]))
        owners = tuple((self.owner if parent == 0 else '', '') for parent in parents[free])
        clear = (yield from self.check(values, pairs, owners)) if len(pairs) else np.array([], dtype=bool)
        passed = free.copy(); passed[free] = clear
        for parent in parents[~passed]: self.domains[int(parent)] = 8*self.scale
        return (yield from self.append(parents[free][clear], candidates[free][clear]))

    def append(self, parents, candidates):
        added = []
        for first in range(0, len(candidates), 128):
            for parent, point in zip(parents[first:first+128], candidates[first:first+128]):
                key = tuple(np.round(point, 10))
                if key in self.seen: continue
                self.seen.add(key); added.append(len(self.points)); self.points.append(point)
                self.parents.append(int(parent)); self.domains.append(np.inf)
            yield 'PIN_EXIT_APPEND'
        self.stats['accepted'] += len(added)
        return added

    def propose(self, batch):
        distance = (8., 16., 32., 64.)[min(batch//32, 3)]*self.scale
        targets = self.rng.uniform(-distance, distance, (32, 3))+self.point
        targets[::4] = self.goals[self.rng.integers(len(self.goals), size=len(targets[::4]))]
        self.stats['targets'] += len(targets); points = np.asarray(self.points)
        parents, usable = yield from nearest_parents(targets, points, self.domains)
        parents, targets = parents[usable], targets[usable]; vectors = targets-points[parents]
        step = self.scale*np.where((parents == 0) & bool(self.owner), 2.5, np.resize((.5,1.,2.,4.),len(parents)))
        candidates = points[parents]+vectors*np.minimum(1., step/np.maximum(np.linalg.norm(vectors, axis=1), 1e-15))[:, None]
        return parents, candidates

    def connect(self, added):
        if not added or not len(self.goals): return None
        values = np.vstack((self.points, self.goals)); offset = len(self.points)
        for first in range(0, len(added), 32):
            nodes = np.asarray(added[first:first+32]); distances = np.linalg.norm(values[nodes, None]-self.goals, axis=2)
            nearest = np.argsort(distances, axis=1, kind='stable')[:, :32]
            pairs = np.column_stack((np.repeat(nodes, nearest.shape[1]), (nearest+offset).ravel()))
            yield 'PIN_EXIT_NEIGHBORS'
            clear = yield from self.check(values, pairs, (('', ''),)*len(pairs))
            if clear.any():
                parent, goal = pairs[np.flatnonzero(clear)[0]]
                return self.path(int(parent)), int(goal-offset)
        return None

    def path(self, index):
        indices = [index]
        while self.parents[indices[-1]] != -1: indices.append(self.parents[indices[-1]])
        return tuple(tuple(self.points[i]) for i in reversed(indices))


def goal_forest(tree):
    forest = ExitTree(tree.point, '', tree.points[1:] or tree.goals, tree.validate, tree.scale, tree.seed+1)
    forest.points = list(tree.goals.copy()); forest.parents = [-1]*len(forest.points)
    forest.domains = [np.inf]*len(forest.points)
    forest.seen = {tuple(np.round(point, 10)) for point in forest.points}
    return forest


def grow_pair(tree, forest, batch):
    for active, other in ((tree, forest), (forest, tree)):
        if len(other.points) > 1: active.goals = np.asarray(other.points[1:])
        parents, candidates = yield from active.propose(batch)
        active.stats['batches'] += 1
        yield 'PIN_EXIT_GROW'
        added = yield from active.accept(parents, candidates)
        result = yield from connect_trees(active, other, added)
        if result is not None: return assemble_trees(tree, forest, *result, active is forest)
    return None


def nearest_parents(targets, points, domains):
    parents = []; usable = []; limits = np.asarray(domains)[None, :]
    for first in range(0, len(targets), 8):
        lengths = np.linalg.norm(targets[first:first+8, None]-points[None, :], axis=2)
        metric = np.where(lengths <= limits, lengths, np.inf)
        indices = np.argmin(metric, axis=1)
        parents.extend(indices); usable.extend(np.isfinite(metric[np.arange(len(indices)), indices]))
        yield 'PIN_EXIT_GROW_NEAREST'
    return np.asarray(parents), np.asarray(usable)


def connect_trees(active, other, added):
    values = np.vstack((active.points, other.points)); offset = len(active.points)
    eligible = np.arange(int(bool(other.owner)), len(other.points))
    if not len(eligible): return None
    for first in range(0, len(added), 32):
        nodes = np.asarray(added[first:first+32]); distances = np.linalg.norm(values[nodes,None]-np.asarray(other.points)[eligible],axis=2)
        nearest = eligible[np.argsort(distances, axis=1, kind='stable')[:, :32]]
        pairs = np.column_stack((np.repeat(nodes, nearest.shape[1]), (nearest+offset).ravel()))
        yield 'PIN_EXIT_NEIGHBORS'
        clear = yield from active.check(values, pairs, (('', ''),)*len(pairs))
        if clear.any():
            parent, goal = pairs[np.flatnonzero(clear)[0]]
            return int(parent), int(goal-offset)
    return None


def assemble_trees(tree, forest, first, second, reverse):
    a, b = (second, first) if reverse else (first, second); root = b
    while forest.parents[root] != -1: root = forest.parents[root]
    chain = (*tree.path(a), *tuple(reversed(forest.path(b)))[:-1])
    return chain, root
