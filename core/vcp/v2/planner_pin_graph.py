"""Request-local collision proofs and graph traversal for pin-exit recovery."""

from collections import deque
from dataclasses import dataclass, field
import numpy as np
from . import planner as p
from .planner_pin_tree import PIN_EXIT_POLICY
from .collision_native import native_roadmap_nearest_batch
from . import planner_preparation as prep


@dataclass
class PinExitGraph:
    state: object
    start: object
    end: object
    policy: object = PIN_EXIT_POLICY
    edge_results: dict = field(default_factory=dict)
    queries: int = 0
    cache_hits: int = 0

    def validate(self, values, pairs, owners):
        values = np.asarray(values, dtype=np.float64); result = np.empty(len(pairs), dtype=bool)
        for first in range(0, len(pairs), self.policy.query_batch):
            batch = pairs[first:first+self.policy.query_batch]; roles = owners[first:first+len(batch)]
            clear = self.checked_batch(values, batch, roles)
            result[first:first+len(batch)] = clear; self.queries += len(batch)
            yield 'PIN_EXIT_COLLISION'
        return result

    def checked_batch(self, values, batch, roles):
        span, threshold = p._state_contact_span(self.state), p._radius(self.state)-p._slack(self.state)
        result = self.state.native_world.validate(values, batch, roles, span, threshold)
        selected = [i for i, owners in enumerate(roles) if any(owners)]
        if not selected: return result.clear
        probes, rows = p._owner_chord_probes(values, [batch[i] for i in selected], [roles[i] for i in selected],
                                            span, threshold, [result.clear[i] for i in selected])
        failures = p._owner_probe_failures(self.state.native_world, probes, rows, p._collider_owner_map(self.state.request))
        failures = tuple((selected[i], blocker) for i, blocker in failures)
        return p._reject_owner_chords(result, failures).clear

    def checked(self, points, graph):
        pairs = yield from graph_pairs(graph)
        for first in range(0, len(pairs), self.policy.query_batch):
            selected = [tuple(map(int, pair)) for pair in pairs[first:first+self.policy.query_batch]]
            batch = [pair for pair in selected if pair not in self.edge_results]
            self.cache_hits += len(selected)-len(batch)
            owners = tuple(p._graph_owners(i, j, self.start.owner_id, self.end.owner_id) for i, j in batch)
            clear = yield from self.validate(points, batch, owners)
            self.edge_results.update(zip(batch, map(bool, clear)))
        rows = []
        for first in range(0, len(graph), 64):
            rows.extend(tuple(j for j in row if self.edge_results.get((min(i,j),max(i,j)), False))
                        for i, row in enumerate(graph[first:first+64], first))
            yield 'PIN_EXIT_GRAPH_FILTER'
        return tuple(rows)


def graph_pairs(graph):
    chunks = []
    for first in range(0, len(graph), 64):
        pairs = np.asarray([(min(i,j), max(i,j)) for i, row in enumerate(graph[first:first+64], first)
                            for j in row if i != j], dtype=np.uint64).reshape(-1, 2)
        chunks.append(pairs[:, 0]*np.uint64(1 << 32)+pairs[:, 1])
        yield 'PIN_EXIT_GRAPH_PAIRS'
    ordered = np.unique(np.concatenate(chunks)) if chunks else np.empty(0, dtype=np.uint64)
    result = np.column_stack((ordered >> np.uint64(32), ordered & np.uint64(0xffffffff)))
    yield 'PIN_EXIT_GRAPH_ORDER'
    return result


def augmented_neighbors(points, original, limit=48):
    rows = [set(row) for row in original]+[set() for _ in range(len(points)-len(original))]
    values = np.asarray(points)
    for first in range(len(original), len(points), 32):
        nearest = native_roadmap_nearest_batch(values, first, min(32, len(points)-first), limit)
        for i, neighbors in enumerate(nearest, first):
            rows[i].update((0, 1)); rows[0].add(i); rows[1].add(i)
            for j in neighbors: rows[i].add(int(j)); rows[int(j)].add(i)
        yield 'PIN_EXIT_GRAPH_NEIGHBORS'
    result = []
    for first in range(0, len(rows), 64):
        result.extend(tuple(sorted(row)) for row in rows[first:first+64])
        yield 'PIN_EXIT_GRAPH_ROWS'
    return tuple(result)


def checked_anchors(state, points, graph, start, end):
    values = np.asarray(points); pairs = prep.anchor_pairs(graph); flags = []
    yield 'PIN_EXIT_ANCHOR_PAIRS'
    for first in range(0, len(pairs), 128):
        batch = pairs[first:first+128]
        owners = tuple(p._graph_owners(int(a), int(b), start.owner_id, end.owner_id) for a, b in batch)
        flags.extend(prep.checked_edges(state, values, batch, owners))
        yield 'PIN_EXIT_ANCHOR_VALIDATE'
    return prep.filtered_graph(graph, pairs, flags)


def component(graph, start):
    parents = {start: -1}; pending = deque((start,))
    while pending:
        for _ in range(min(64, len(pending))):
            node = pending.popleft()
            for other in graph[node]:
                if other not in parents: parents[other] = node; pending.append(other)
        yield 'PIN_EXIT_COMPONENT'
    return parents


def graph_path(points, parents, node):
    path = [node]
    while parents[path[-1]] != -1: path.append(parents[path[-1]])
    return tuple(tuple(points[i]) for i in reversed(path))


def join_route(state, points, groups, goals, side, found, start, end):
    chain, goal = found; remainder = graph_path(points, groups[1-side], goals[goal])
    raw = (*chain, *reversed(remainder))
    if side == 1: raw = tuple(reversed(raw))
    safe = p._route_clear(state, raw, start.owner_id, end.owner_id)
    yield 'PIN_EXIT_CORRIDOR_VALIDATE'
    if not safe: return None
    route = p._shortcut_route(state, raw, start.owner_id, end.owner_id)
    yield 'PIN_EXIT_SHORTCUT'
    safe = p._route_clear(state, route, start.owner_id, end.owner_id)
    yield 'PIN_EXIT_CORRIDOR_VALIDATE'
    return route if safe else None
