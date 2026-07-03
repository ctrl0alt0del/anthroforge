from dataclasses import dataclass
from heapq import heappop, heappush


DIRECT = "DIRECT"
ROADMAP = "ROADMAP"
LOCAL_FALLBACK = "LOCAL_FALLBACK"


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


def plan_route(oracle, anchors):
    results = [_plan_segment(oracle, seg) for seg in _segments(anchors)]
    return PlannerResult(_merge_paths(results), _merge_mode(results), _merge_active_ids(results))


def _segments(anchors):
    return [PlannerSegment(anchors[i], anchors[i + 1]) for i in range(max(0, len(anchors) - 1))]


def _plan_segment(oracle, segment):
    active = oracle.active_colliders_for_segment(segment.start.point, segment.end.point, padding=_corridor_pad(oracle))
    if oracle.segment_visible(segment.start.point, segment.end.point, _owners(segment), active):
        return PlannerResult(_segment_points(segment), DIRECT, _active_ids(active))
    return _roadmap_result(oracle, segment, active, False) or _roadmap_result(oracle, segment, active, True) or _fallback_result(segment, active)


def _corridor_pad(oracle):
    return max(0.05, float(oracle.clearance), float(oracle.margin) * 4.0)


def _owners(segment):
    return segment.start.owner_id, segment.end.owner_id


def _segment_points(segment):
    return [segment.start.point.copy(), segment.end.point.copy()]


def _roadmap_result(oracle, segment, active, dense):
    path = _roadmap_path(oracle, segment, active, dense)
    return None if path is None else PlannerResult(_shortcut_path(oracle, path, active), ROADMAP, _active_ids(active))


def _fallback_result(segment, active):
    return PlannerResult(_segment_points(segment), LOCAL_FALLBACK, _active_ids(active))


def _roadmap_path(oracle, segment, active, dense):
    nodes = _roadmap_nodes(oracle, segment, active, dense)
    graph = _visible_graph(oracle, nodes, active)
    path = _a_star(nodes, graph)
    return None if path is None else [nodes[i].point.copy() for i in path]


def _roadmap_nodes(oracle, segment, active, dense):
    nodes = [RoadmapNode(segment.start.point.copy(), segment.start.owner_id), RoadmapNode(segment.end.point.copy(), segment.end.owner_id)]
    for collider in active:
        nodes.extend(RoadmapNode(point.copy(), "") for point in oracle.shell_nodes(collider, dense=dense))
    return _dedupe_nodes(nodes)


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
    goal, heap, came, dist, seen = len(nodes) - 1, [(0.0, 0)], {}, {0: 0.0}, set()
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


def _shortcut_path(oracle, points, active):
    if len(points) <= 2:
        return [point.copy() for point in points]
    return _shortcut_walk(oracle, [point.copy() for point in points], active)


def _shortcut_walk(oracle, points, active):
    out, i = [points[0].copy()], 0
    while i < len(points) - 1:
        j = _furthest_visible(oracle, points, active, i)
        out.append(points[j].copy())
        i = j
    return out


def _furthest_visible(oracle, points, active, index):
    for j in range(len(points) - 1, index, -1):
        if oracle.segment_visible(points[index], points[j], ("", ""), active):
            return j
    return index + 1


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
