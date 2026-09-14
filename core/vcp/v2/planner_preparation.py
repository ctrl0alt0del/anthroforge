"""Expanded candidate preparation; collision policy stays in the shared validator."""

from time import perf_counter
import numpy as np

from . import planner as p
from .collision_native import native_roadmap_neighbors


def graph_csr(graph):
    sizes = np.fromiter(map(len, graph), dtype=np.int64, count=len(graph))
    offsets = np.concatenate(([0], np.cumsum(sizes)))
    links = np.fromiter((j for row in graph for j in row), dtype=np.int64, count=int(offsets[-1]))
    return offsets, links


def unique_points(original, candidates):
    if not len(candidates): return tuple(original)
    values = np.asarray((*original, *candidates), dtype=np.float64)
    _keys, first = np.unique(np.round(values, 10), axis=0, return_index=True)
    indices = sorted(int(i) for i in first if i >= len(original))
    return (*original, *(values[i] for i in indices))


def native_neighbors(points, original, limit=48):
    offsets, links = graph_csr(original)
    starts, rows = native_roadmap_neighbors(points, offsets, links, limit)
    return tuple(tuple(rows[starts[i]:starts[i+1]].tolist()) for i in range(len(points)))


def shell_samples(state, start, end):
    first, last = np.asarray(start.point), np.asarray(end.point)
    for dense in (False, True):
        for collider in p._corridor_colliders(state.request.colliders, first, last, dense):
            yield p._collider_shell(state, collider, first, last, dense)


def valid_points(state, combined, first, last):
    pairs = tuple((i, i) for i in range(first, last))
    result = state.native_world.validate(combined, pairs, (('', ''),) * len(pairs),
        p._state_contact_span(state), p._radius(state)-p._slack(state))
    state.candidate_pairs += result.candidate_pairs; state.tested_pairs += result.tested_pairs
    return tuple(combined[i] for (i, _), clear in zip(pairs, result.clear) if clear)


def anchor_pairs(graph):
    offsets, links = graph_csr(graph)
    sources = np.repeat(np.arange(len(graph), dtype=np.int64), np.diff(offsets))
    selected = (sources != links) & ((sources < 2) | (links < 2))
    pairs = np.column_stack((sources[selected], links[selected])); pairs.sort(axis=1)
    return np.unique(pairs, axis=0)


def owner_probes(values, edges, owners, span, threshold, clear):
    flags = np.asarray([[bool(a), bool(b)] for a, b in owners], dtype=bool)
    segments = values[edges]; origin = segments[:, 0]; delta = segments[:, 1]-origin
    divisor = np.maximum(np.linalg.norm(delta, axis=1), 1e-12)
    low = np.where(flags[:, 0], float(span)/divisor, 0.)
    high = np.where(flags[:, 1], 1.-float(span)/divisor, 1.)
    offset = np.minimum((high-low)*.1, np.maximum(1e-9, float(threshold)/divisor))
    factors = np.column_stack((low+offset, high-offset))
    mask = flags & np.asarray(clear)[:, None] & (low < high)[:, None]
    coordinates = origin[:, None, :] + factors[:, :, None]*delta[:, None, :]
    positions, side = np.nonzero(mask)
    rows = tuple((int(i), str(owners[i][j])) for i, j in zip(positions, side))
    return coordinates[mask], rows


def checked_edges(state, points, pairs, owners):
    tick = perf_counter(); threshold = p._radius(state)-p._slack(state)
    result = state.native_world.validate(points, pairs, owners, p._state_contact_span(state), threshold)
    probes, rows = owner_probes(points, pairs, owners, p._state_contact_span(state), threshold, result.clear)
    failures = p._owner_probe_failures(state.native_world, probes, rows, p._collider_owner_map(state.request))
    result = p._reject_owner_chords(result, failures)
    store_edges(state, points, pairs, owners, result.clear)
    state.tested_edges += len(pairs); state.rejected_edges += sum(not v for v in result.clear)
    state.edge_batches += int(bool(len(pairs))); state.candidate_pairs += result.candidate_pairs
    state.tested_pairs += result.tested_pairs; state.native_collision_ms += 1000*(perf_counter()-tick)
    return result.clear


def store_edges(state, points, pairs, owners, flags):
    keys = tuple(map(tuple, np.round(points, 12)))
    state.edge_cache.update(((keys[a], keys[b], str(first or ''), str(second or '')), bool(clear))
        for (a, b), (first, second), clear in zip(pairs, owners, flags))


def filtered_graph(graph, pairs, clear):
    blocked = {tuple(map(int, edge)) for edge, allowed in zip(pairs, clear) if not allowed}
    rows = [tuple(j for j in graph[i] if (min(i, j), max(i, j)) not in blocked) for i in range(2)]
    rows.extend(tuple(j for j in row if j >= 2 or (j, i) not in blocked) for i, row in enumerate(graph[2:], 2))
    return tuple(rows)


def checked_anchor_steps(state, points, graph, start, end):
    values = np.asarray(points); pairs = anchor_pairs(graph); flags = []
    for first in range(0, len(pairs), 512):
        batch = pairs[first:first+512]
        owners = tuple(p._graph_owners(int(a), int(b), start.owner_id, end.owner_id) for a, b in batch)
        flags.extend(checked_edges(state, values, batch, owners))
        yield "ANCHOR_VALIDATION"
    return filtered_graph(graph, pairs, flags)


class NativeRoadmapPreparation:
    unique = staticmethod(unique_points)
    neighbors = staticmethod(native_neighbors)
    anchors = staticmethod(checked_anchor_steps)


NATIVE_PREPARATION = NativeRoadmapPreparation()
