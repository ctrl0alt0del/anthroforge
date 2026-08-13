"""Deadline-aware adapter for the existing deterministic Fiber roadmap."""

from dataclasses import dataclass
from time import perf_counter

from .fiber_collision import _segment_clear
from .fiber_planner import (
    DIRECT, ROADMAP, PlannerResult, RoadmapNode, _a_star, _active_ids,
    _corridor_pad, _dedupe_nodes, _fallback_result, _limit_roadmap_nodes,
    _initial_colliders, _merge_active_ids, _merge_colliders, _merge_mode,
    _merge_paths, _owners, _result_with_active, _route_colliders,
    _segment_points, _segments, _shortcut_path,
)


@dataclass
class ProgressivePlanner:
    iterator: object
    result: object = None
    done: bool = False
    elapsed_ms: float = 0.0


def begin_progressive_plan(oracle, anchors, allow_dense=True):
    iterator = _plan_steps(oracle, tuple(anchors or ()), bool(allow_dense))
    return ProgressivePlanner(iterator)


def advance_progressive_plan(planner, deadline):
    started = perf_counter()
    _advance_until(planner, deadline)
    planner.elapsed_ms += (perf_counter() - started) * 1000.0
    return planner.done


def _advance_until(planner, deadline):
    ran = False
    while not planner.done and (not ran or perf_counter() < deadline):
        _advance_once(planner)
        ran = True


def _advance_once(planner):
    try:
        next(planner.iterator)
    except StopIteration as stop:
        planner.result, planner.done = stop.value, True


def _plan_steps(oracle, anchors, allow_dense):
    results = []
    for segment in _segments(anchors):
        result = yield from _segment_steps(oracle, segment, allow_dense)
        results.append(result)
    return PlannerResult(_merge_paths(results), _merge_mode(results),
                         _merge_active_ids(results))


def _segment_steps(oracle, segment, allow_dense):
    active = _initial_colliders(oracle, segment)
    while True:
        result = yield from _segment_active_steps(oracle, segment, active, allow_dense)
        expanded = _route_colliders(oracle, result.points, active)
        merged = _merge_colliders(active, expanded)
        if len(merged) == len(active):
            return result
        if (yield from _route_visible_steps(oracle, segment, result.points, merged)):
            return _result_with_active(result, merged)
        active = merged
        yield None


def _route_visible_steps(oracle, segment, points, colliders):
    for index in range(len(points) - 1):
        owners = _route_edge_owners(segment, points, index)
        if not (yield from _visible_steps(
                oracle, points[index], points[index + 1], owners, colliders)):
            return False
    return True


def _route_edge_owners(segment, points, index):
    first = segment.start.owner_id if index == 0 else ""
    last = segment.end.owner_id if index + 1 == len(points) - 1 else ""
    return first, last


def _segment_active_steps(oracle, segment, blockers, allow_dense):
    visible = yield from _visible_steps(
        oracle, segment.start.point, segment.end.point, _owners(segment), blockers)
    if visible:
        return PlannerResult(_segment_points(segment), DIRECT, _active_ids(blockers))
    result = yield from _roadmap_steps(oracle, segment, blockers, False)
    return result or (yield from _dense_steps(oracle, segment, blockers, allow_dense))


def _dense_steps(oracle, segment, active, allow_dense):
    if allow_dense:
        result = yield from _roadmap_steps(oracle, segment, active, True)
        if result is not None:
            return result
    return _fallback_result(segment, active)


def _roadmap_steps(oracle, segment, active, dense):
    shell = yield from _shell_steps(oracle, segment, active)
    nodes = yield from _node_steps(oracle, segment, shell, dense)
    graph = {index: [] for index in range(len(nodes))}
    yield from _graph_steps(oracle, nodes, active, graph)
    path = _a_star(nodes, graph)
    if path is None:
        return None
    points = [nodes[index].point.copy() for index in path]
    route = _shortcut_path(oracle, points, active, _owners(segment))
    return PlannerResult(route, ROADMAP, _active_ids(active))


def _graph_steps(oracle, nodes, active, graph):
    for first in range(len(nodes) - 1):
        for second in range(first + 1, len(nodes)):
            yield from _edge_steps(oracle, nodes, active, graph, first, second)


def _visible_steps(oracle, start, end, owners, colliders):
    for collider in tuple(colliders or ()):
        if not _segment_clear(oracle, collider, start, end, owners):
            return False
        yield None
    return True


def _shell_steps(oracle, segment, active):
    blockers = []
    for collider in tuple(active or ()):
        visible = yield from _visible_steps(
            oracle, segment.start.point, segment.end.point, _owners(segment), (collider,))
        None if visible else blockers.append(collider)
    return tuple(blockers) or active


def _node_steps(oracle, segment, active, dense):
    nodes = [RoadmapNode(segment.start.point.copy(), segment.start.owner_id),
             RoadmapNode(segment.end.point.copy(), segment.end.owner_id)]
    for collider in tuple(active or ()):
        nodes.extend(RoadmapNode(point.copy(), "")
                     for point in oracle.shell_nodes(collider, dense=dense))
        yield None
    return _limit_roadmap_nodes(_dedupe_nodes(nodes), dense)


def _edge_steps(oracle, nodes, active, graph, first, second):
    visible = yield from _visible_steps(
        oracle, nodes[first].point, nodes[second].point,
        (nodes[first].owner_id, nodes[second].owner_id), active)
    if not visible:
        return
    cost = (nodes[second].point - nodes[first].point).length
    graph[first].append((second, cost))
    graph[second].append((first, cost))
