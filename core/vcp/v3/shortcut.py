"""Optional collision-validated ROADMAP seed shortcut for Fiber V3."""

from dataclasses import dataclass

import numpy as np

from .policy import V3ShortcutMode


@dataclass(frozen=True)
class V3ShortcutTrace:
    mode: str = "OFF"
    attempts: int = 0
    accepted: int = 0
    candidate_pairs: int = 0
    tested_pairs: int = 0
    route_nodes_before: int = 0
    route_nodes_after: int = 0


def apply_v3_shortcut(request, planner, seed, pins, world, mode):
    mode = V3ShortcutMode(mode)
    if mode is V3ShortcutMode.OFF: return seed, V3ShortcutTrace()
    shortened, values = _shortcut_spans(request, planner, seed, pins, world)
    trace = V3ShortcutTrace(mode.value, *values)
    return (shortened if mode is V3ShortcutMode.ON else seed), trace


def _shortcut_spans(request, planner, seed, pins, world):
    stats = [0, 0, 0, 0, 0, 0]; rows = []
    for span, (first, last) in enumerate(zip(pins[:-1], pins[1:])):
        block = np.asarray(seed[first:last + 1]); stats[4] += len(block)
        fixed = _shortcut_block(request, planner, span, block, world, stats)
        stats[5] += _control_count(fixed); rows.extend(fixed if not rows else fixed[1:])
    return np.asarray(rows, dtype=np.float64), tuple(stats)


def _shortcut_block(request, planner, span, points, world, stats):
    if planner.spans[span].branch.value != "ROADMAP": return points.copy()
    owners = request.anchors[span].owner_id, request.anchors[span + 1].owner_id
    output, index = points.copy(), 0
    while index < len(points) - 1:
        candidate, chord = _furthest_clear(request, points, index, owners, world, stats)
        stats[1] += int(candidate > index + 1); output[index:candidate + 1] = chord; index = candidate
    return output


def _furthest_clear(request, points, index, owners, world, stats):
    for candidate in range(len(points) - 1, index, -1):
        chord = _chord(points[index], points[candidate], candidate - index)
        local = (owners[0] if index == 0 else "", owners[1] if candidate + 1 == len(points) else "")
        if _clear(request, chord, local, world, stats): return candidate, chord
    return index + 1, _chord(points[index], points[index + 1], 1)


def _clear(request, points, owners, world, stats):
    edges = tuple((index, index + 1) for index in range(len(points) - 1))
    edge_owners = tuple((owners[0] if not index else "",
                         owners[1] if index + 1 == len(edges) else "") for index in range(len(edges)))
    result = world.validate(points, edges, edge_owners, _owner_span(request, points), _threshold(request))
    stats[0] += 1; stats[2] += result.candidate_pairs; stats[3] += result.tested_pairs
    return bool(all(result.clear))


def _owner_span(request, points):
    radius = request.collision_policy.collision_radius
    slack = request.tolerances.clearance_slack
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    return max(4.0 * slack, 2.5 * radius, float(np.max(lengths)), 1.0e-9)


def _threshold(request):
    return max(0.0, request.collision_policy.collision_radius - request.tolerances.clearance_slack)


def _chord(first, second, edges):
    factors = np.linspace(0.0, 1.0, int(edges) + 1)[:, None]
    return first + factors * (second - first)


def _control_count(points):
    if len(points) < 2: return len(points)
    turns = np.linalg.norm(np.diff(points, n=2, axis=0), axis=1)
    return 2 + int(np.count_nonzero(turns > 1.0e-10))
