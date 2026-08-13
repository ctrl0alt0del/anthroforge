from dataclasses import dataclass
from heapq import heappop, heappush


DIRECT = "DIRECT"
ROADMAP = "ROADMAP"
LOCAL_FALLBACK = "LOCAL_FALLBACK"
_ROADMAP_NODE_LIMIT = 96
_ROADMAP_NODE_LIMIT_DENSE = 240


@dataclass(frozen=True)
class PlannerAnchor:
    point: object
    owner_id: str = ""
    attach_raw: str = ""


@dataclass(frozen=True)
class PlannerSegment:
    start: PlannerAnchor
    end: PlannerAnchor


@dataclass(frozen=True)
class RoadmapNode:
    point: object
    owner_id: str = ""


@dataclass
class PlannerResult:
    points: list
    mode: str
    active_ids: tuple


def plan_route(oracle, anchors, allow_dense=True):
    results = [_plan_segment(oracle, seg, allow_dense) for seg in _segments(anchors)]
    return PlannerResult(_merge_paths(results), _merge_mode(results), _merge_active_ids(results))


def _segments(anchors):
    return [PlannerSegment(anchors[i], anchors[i + 1]) for i in range(max(0, len(anchors) - 1))]


def _plan_segment(oracle, segment, allow_dense=True):
    active = _initial_colliders(oracle, segment)
    while True:
        result = _plan_segment_active(oracle, segment, active, allow_dense)
        expanded = _route_colliders(oracle, result.points, active)
        merged = _merge_colliders(active, expanded)
        if len(merged) == len(active):
            return result
        if _route_visible(oracle, result.points, _owners(segment), merged):
            return _result_with_active(result, merged)
        active = merged


def _plan_segment_active(oracle, segment, active, allow_dense):
    if oracle.segment_visible(segment.start.point, segment.end.point, _owners(segment), active):
        return PlannerResult(_segment_points(segment), DIRECT, _active_ids(active))
    sparse = _roadmap_result(oracle, segment, active, False)
    return sparse or _dense_or_fallback(oracle, segment, active, allow_dense)


def _initial_colliders(oracle, segment):
    active = oracle.active_colliders_for_segment(
        segment.start.point, segment.end.point, padding=_corridor_pad(oracle))
    return tuple(active or ())


def _route_colliders(oracle, points, fallback):
    if not hasattr(oracle, "active_colliders_for_polyline"):
        return fallback
    return oracle.active_colliders_for_polyline(points, padding=_corridor_pad(oracle))


def _merge_colliders(first, second):
    out, seen = [], set()
    for collider in (*tuple(first or ()), *tuple(second or ())):
        key = _collider_key(collider)
        if key not in seen:
            seen.add(key)
            out.append(collider)
    return tuple(out)


def _collider_key(collider):
    sid = collider.get("sid", "") if hasattr(collider, "get") else ""
    return ("sid", str(sid)) if sid else ("id", id(collider))


def _route_visible(oracle, points, owners, colliders):
    for index in range(len(points) - 1):
        edge_owners = _edge_owners(points, index, index + 1, owners)
        if not oracle.segment_visible(points[index], points[index + 1], edge_owners, colliders):
            return False
    return True


def _result_with_active(result, active):
    return PlannerResult([point.copy() for point in result.points],
                         result.mode, _active_ids(active))


def _dense_or_fallback(oracle, segment, active, allow_dense):
    if allow_dense:
        return _roadmap_result(oracle, segment, active, True) or _fallback_result(segment, active)
    return _fallback_result(segment, active)


def _corridor_pad(oracle):
    if hasattr(oracle, "active_padding"):
        return float(oracle.active_padding())
    return max(0.05, float(oracle.clearance) * 2.0, float(oracle.margin) * 4.0)


def _owners(segment):
    return segment.start.owner_id, segment.end.owner_id


def _segment_points(segment):
    return [segment.start.point.copy(), segment.end.point.copy()]


def _roadmap_result(oracle, segment, active, dense):
    path = _roadmap_path(oracle, segment, _roadmap_shell_colliders(oracle, segment, active), active, dense)
    return None if path is None else PlannerResult(_shortcut_path(oracle, path, active, _owners(segment)), ROADMAP, _active_ids(active))


def _fallback_result(segment, active):
    return PlannerResult(_segment_points(segment), LOCAL_FALLBACK, _active_ids(active))


def _roadmap_shell_colliders(oracle, segment, active):
    blockers = tuple(c for c in active if not oracle.segment_visible(segment.start.point, segment.end.point, _owners(segment), (c,)))
    return blockers or active


def _roadmap_path(oracle, segment, shell_colliders, active, dense):
    nodes = _roadmap_nodes(oracle, segment, shell_colliders, dense)
    graph = _visible_graph(oracle, nodes, active)
    path = _a_star(nodes, graph)
    return None if path is None else [nodes[i].point.copy() for i in path]


def _roadmap_nodes(oracle, segment, active, dense):
    nodes = [RoadmapNode(segment.start.point.copy(), segment.start.owner_id), RoadmapNode(segment.end.point.copy(), segment.end.owner_id)]
    for collider in active:
        nodes.extend(RoadmapNode(point.copy(), "") for point in oracle.shell_nodes(collider, dense=dense))
    return _limit_roadmap_nodes(_dedupe_nodes(nodes), dense)


def _limit_roadmap_nodes(nodes, dense):
    limit = _ROADMAP_NODE_LIMIT_DENSE if dense else _ROADMAP_NODE_LIMIT
    if len(nodes) <= limit:
        return nodes
    return nodes[:2] + _sample_even(nodes[2:], limit - 2)


def _sample_even(items, limit):
    values = list(items or ())
    if len(values) <= int(limit):
        return values
    last = len(values) - 1
    return [values[min(last, round(i * last / float(max(1, int(limit) - 1))))] for i in range(int(limit))]


def _dedupe_nodes(nodes):
    seen, out = set(), []
    for node in nodes:
        key = _node_key(node.point)
        if key not in seen:
            seen.add(key)
            out.append(node)
    return out


def _node_key(point):
    return round(point.x, 5), round(point.y, 5), round(point.z, 5)


def _visible_graph(oracle, nodes, active):
    graph = {i: [] for i in range(len(nodes))}
    for i in range(len(nodes) - 1):
        for j in range(i + 1, len(nodes)):
            _append_edge(oracle, nodes, active, graph, i, j)
    return graph


def _append_edge(oracle, nodes, active, graph, i, j):
    if not oracle.segment_visible(nodes[i].point, nodes[j].point, (nodes[i].owner_id, nodes[j].owner_id), active):
        return
    cost = (nodes[j].point - nodes[i].point).length
    graph[i].append((j, cost))
    graph[j].append((i, cost))


def _a_star(nodes, graph):
    goal, heap, came, dist, seen = 1, [(0.0, 0)], {}, {0: 0.0}, set()
    while heap:
        _score, node = heappop(heap)
        if node == goal:
            return _reconstruct_path(came, goal)
        if node in seen:
            continue
        seen.add(node)
        for nxt, cost in graph.get(node, ()):
            _push_neighbor(nodes, heap, came, dist, node, nxt, cost, goal)
    return None


def _push_neighbor(nodes, heap, came, dist, node, nxt, cost, goal):
    cand = dist[node] + cost
    if cand >= dist.get(nxt, 1.0e18):
        return
    dist[nxt], came[nxt] = cand, node
    heappush(heap, (cand + _heuristic(nodes[nxt].point, nodes[goal].point), nxt))


def _heuristic(a, b):
    return (b - a).length


def _reconstruct_path(came, goal):
    node, out = goal, [goal]
    while node in came:
        node = came[node]
        out.append(node)
    return list(reversed(out))


def _shortcut_path(oracle, points, active, owners=("", "")):
    if len(points) <= 2:
        return [point.copy() for point in points]
    walked = _shortcut_walk(oracle, [point.copy() for point in points], active, owners)
    return _relax_path(oracle, walked, active, owners=owners)


def _shortcut_walk(oracle, points, active, owners=("", "")):
    out, i = [points[0].copy()], 0
    while i < len(points) - 1:
        j = _furthest_visible(oracle, points, active, i, owners)
        out.append(points[j].copy())
        i = j
    return out


def _furthest_visible(oracle, points, active, index, owners=("", "")):
    for j in range(len(points) - 1, index, -1):
        edge_owners = _edge_owners(points, index, j, owners)
        if oracle.segment_visible(points[index], points[j], edge_owners, active):
            return j
    return index + 1


def _edge_owners(points, start, end, owners):
    values = tuple(owners or ())
    first = str(values[0] or "") if start == 0 and values else ""
    last = str(values[1] or "") if end == len(points) - 1 and len(values) > 1 else ""
    return first, last


def _relax_path(oracle, points, active, steps=6, owners=("", "")):
    out = [point.copy() for point in tuple(points or ())]
    if len(out) <= 2:
        return out
    for _step in range(int(steps)):
        changed = _relax_pass(oracle, out, active, owners)
        if not changed:
            break
    return out


def _relax_pass(oracle, points, active, owners=("", "")):
    changed = False
    for index in range(1, len(points) - 1):
        changed = _relax_point(oracle, points, active, index, owners) or changed
    return changed


def _relax_point(oracle, points, active, index, owners=("", "")):
    candidate = (points[index - 1] + points[index + 1]) * 0.5
    if not _relax_visible(oracle, points, active, index, candidate, owners):
        return False
    if _local_path_len(points[index - 1], candidate, points[index + 1]) >= _local_path_len(points[index - 1], points[index], points[index + 1]):
        return False
    points[index] = candidate
    return True


def _relax_visible(oracle, points, active, index, candidate, owners=("", "")):
    prev_owners = _edge_owners(points, index - 1, index, owners)
    next_owners = _edge_owners(points, index, index + 1, owners)
    prev_ok = oracle.segment_visible(points[index - 1], candidate, prev_owners, active)
    next_ok = oracle.segment_visible(candidate, points[index + 1], next_owners, active)
    return bool(prev_ok and next_ok)


def _local_path_len(a, b, c):
    return (b - a).length + (c - b).length


def _merge_paths(results):
    out = []
    for idx, result in enumerate(results):
        out.extend(_path_tail(result.points, idx > 0))
    return out


def _path_tail(points, drop_first):
    tail = points[1:] if drop_first and len(points) > 1 else points
    return [point.copy() for point in tail]


def _merge_mode(results):
    modes = [result.mode for result in results]
    return LOCAL_FALLBACK if LOCAL_FALLBACK in modes else (ROADMAP if ROADMAP in modes else DIRECT)


def _merge_active_ids(results):
    seen = []
    for result in results:
        for sid in result.active_ids:
            None if sid in seen else seen.append(sid)
    return tuple(seen)


def _active_ids(colliders):
    return tuple(collider["sid"] for collider in colliders)
