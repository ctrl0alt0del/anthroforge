"""Deterministic, Blender-independent route planning for Fiber Solver V2."""

from dataclasses import dataclass, replace
from enum import Enum
from heapq import heappop, heappush
from math import ceil
from time import perf_counter

import numpy as np

from .collision import (V2OwnerContact, build_triangle_snapshot,
                        cached_native_collision_world,
                        collision_backend_status, validate_segment_clearance_batch,
                        validate_static_clearance)
from .contracts import V2Request, V2Termination, V2Topology
from .collision_native import native_mesh_shortest_path
from .planner_anchor_access import anchor_access_candidates, append_access_neighbors, append_access_points


V2_PLANNER_VERSION = "fiber-v2-planner-1"
V2_PLANNER_41_VERSION = "fiber-v2-planner-1.1"
V2_PLANNER_42_VERSION = "fiber-v2-planner-1.2"
V2_PLANNER_43_VERSION = "fiber-v2-planner-1.5"
_SPARSE_LIMIT = 96
_DENSE_LIMIT = 240
_SPARSE_NEIGHBORS = 24
_DENSE_NEIGHBORS = 48
_SURFACE_FACTORS = (1.25, 1.75, 2.5, 4.0, 8.0)


class V2PlannerMode(str, Enum):
    DIRECT = "DIRECT"
    SURFACE = "SURFACE"
    ROADMAP = "ROADMAP"


class V2PlannerBranch(str, Enum):
    DIRECT = "DIRECT"
    SURFACE_BRIDGE = "SURFACE_BRIDGE"
    SURFACE_MESH = "SURFACE_MESH"
    ROADMAP = "ROADMAP"


@dataclass(frozen=True)
class V2PlannerSpan:
    first_edge: int
    edge_count: int
    branch: V2PlannerBranch
    owner_id: str = ""
    lift_factor: float = 0.0
    start_anchor: int = 0
    end_anchor: int = 0


@dataclass(frozen=True)
class V2PlannerDiagnostics:
    candidate_nodes: int = 0
    tested_edges: int = 0
    rejected_edges: int = 0
    corridor_points: int = 0
    candidate_pairs: int = 0
    tested_pairs: int = 0
    planner_ms: float = 0.0
    handoff_ms: float = 0.0
    graph_searches: int = 0
    edge_batches: int = 0
    frontier_edges: int = 0
    graph_metric_builds: int = 0
    graph_expansions: int = 0
    chain_groups: int = 0
    shared_candidates: int = 0
    native_search_ms: float = 0.0
    native_collision_ms: float = 0.0


@dataclass(frozen=True)
class V2PlannerResult:
    termination: V2Termination
    mode: V2PlannerMode
    reference: tuple = ()
    corridor: tuple = ()
    pin_indices: tuple = ()
    contacts: tuple = ()
    collider_ids: tuple = ()
    diagnostics: V2PlannerDiagnostics = V2PlannerDiagnostics()
    message: str = ""
    spans: tuple = ()

    @property
    def succeeded(self):
        return self.termination is V2Termination.CONVERGED


@dataclass
class _PlannerState:
    request: object
    snapshot: object
    edge_cache: dict
    membership_cache: dict
    tested_edges: int = 0
    rejected_edges: int = 0
    candidate_nodes: int = 0
    candidate_pairs: int = 0
    tested_pairs: int = 0
    graph_searches: int = 0
    edge_batches: int = 0
    frontier_edges: int = 0
    graph_metric_builds: int = 0
    graph_expansions: int = 0
    chain_groups: int = 0
    shared_candidates: int = 0
    native_world: object = None
    native_search_ms: float = 0.0
    native_collision_ms: float = 0.0
    owner_contact_factor: float = 2.5


@dataclass(frozen=True)
class _SegmentRoute:
    points: tuple
    mode: V2PlannerMode
    branch: V2PlannerBranch
    owner_id: str = ""
    lift_factor: float = 0.0


def plan_reference(request, snapshot=None):
    """Return a deterministic exact-count planner reference for one V2 request."""
    return _plan_reference(request, snapshot, _plan_segments)


def plan_reference_v41(request, snapshot=None):
    """Return a Package 4.1 batched-lazy exact-count planner reference."""
    return _plan_reference(request, snapshot, _plan_segments_v41)


def plan_reference_v42(request, snapshot=None):
    """Return a Package 4.2 shared-chain planner reference."""
    return _plan_reference(request, snapshot, _plan_segments_v42)


def plan_reference_v43(request, snapshot=None, owner_contact_factor=2.5, native_world=None):
    """Return a Package 4.3 fused-native exact-count planner reference."""
    started = perf_counter(); issue = _configuration_issue(request)
    if issue:
        return _failed(V2Termination.INVALID_CONFIGURATION, issue, started)
    if not collision_backend_status().available:
        return _failed(V2Termination.BACKEND_UNAVAILABLE, "native collision backend unavailable", started)
    state = _v43_state(request, snapshot, owner_contact_factor, native_world)
    invalid = _invalid_anchor(state)
    if invalid:
        return _failed_with_state(state, V2Termination.INVALID_ATTACHMENT, invalid, started)
    return _finish_plan(state, _plan_segments_v41(state), started)


def _v43_state(request, snapshot, owner_contact_factor, native_world=None):
    triangle = snapshot or build_triangle_snapshot(request.colliders)
    world = native_world or cached_native_collision_world(request.colliders)
    return _PlannerState(request, triangle, {}, {}, native_world=world,
                         owner_contact_factor=float(owner_contact_factor))


def _invalid_anchor(state):
    points = np.asarray([anchor.point for anchor in state.request.anchors], dtype=np.float64)
    edges = tuple((index, index) for index in range(len(points)))
    owners = tuple((anchor.owner_id, anchor.owner_id) for anchor in state.request.anchors)
    result = state.native_world.validate(points, edges, owners, _state_contact_span(state),
                                         _radius(state) - _slack(state))
    state.candidate_pairs += result.candidate_pairs; state.tested_pairs += result.tested_pairs
    for index, clear in enumerate(result.clear):
        if not clear:
            return f"authored anchor {index} intersects collider {result.blockers[index] or 'unknown'}"
    return ""


def _plan_reference(request, snapshot, segment_planner):
    started = perf_counter(); issue = _configuration_issue(request)
    if issue:
        return _failed(V2Termination.INVALID_CONFIGURATION, issue, started)
    snapshot = snapshot or build_triangle_snapshot(request.colliders)
    if not collision_backend_status().available:
        return _failed(V2Termination.BACKEND_UNAVAILABLE, "native collision backend unavailable", started)
    state = _PlannerState(request, snapshot, {}, {})
    routes = segment_planner(state)
    return _finish_plan(state, routes, started)


def _configuration_issue(request):
    if not isinstance(request, V2Request):
        return "planner requires a V2Request"
    minimum = 3 if request.settings.topology is V2Topology.CYCLIC else 2
    if len(request.anchors) < minimum:
        return "topology has too few authored anchors"
    if request.settings.node_count < len(request.anchors):
        return "authored anchors cannot fit requested node count"
    return ""


def _failed(reason, message, started, diagnostics=None):
    elapsed = 1000.0 * (perf_counter() - started)
    diag = diagnostics or V2PlannerDiagnostics(planner_ms=elapsed)
    return V2PlannerResult(reason, V2PlannerMode.DIRECT, diagnostics=diag, message=message)


def _plan_segments(state):
    return _plan_segments_with(state, _plan_pair)


def _plan_segments_v41(state):
    return _plan_segments_with(state, _plan_pair_v41)


def _plan_segments_v42(state):
    if _cyclic(state.request):
        return _plan_segments_v41(state)
    output = []
    for first, last, grouped in _ordered_anchor_groups(state.request.anchors):
        routes = _plan_owner_chain(state, first, last) if grouped else _plan_group_pairs(state, first, last)
        if routes is None:
            return None
        output.extend(routes)
    return tuple(output)


def _ordered_anchor_groups(anchors):
    groups, first, count = [], 0, len(anchors)
    while first < count - 1:
        owner = str(anchors[first].owner_id or ""); last = first + 1
        while owner and last < count and str(anchors[last].owner_id or "") == owner:
            last += 1
        grouped = last - first > 2; last = last - 1 if grouped else first + 1
        groups.append((first, last, grouped)); first = last
    return tuple(groups)


def _plan_group_pairs(state, first, last):
    anchors = state.request.anchors; output = []
    for index in range(first, last):
        route = _plan_pair_v41(state, anchors[index], anchors[index + 1])
        if route is None:
            return None
        output.append(route)
    return tuple(output)


def _plan_owner_chain(state, first, last):
    anchors = state.request.anchors[first:last + 1]
    surface = _surface_owner_chain(state, anchors)
    if surface is not None:
        state.chain_groups += 1
        return surface
    shared = _shared_chain_candidates(state, anchors); state.chain_groups += 1
    state.shared_candidates = max(state.shared_candidates, len(shared))
    output = []
    for start, end in zip(anchors[:-1], anchors[1:]):
        route = _plan_chain_pair(state, start, end, shared)
        if route is None:
            return None
        output.append(route)
    return tuple(output)


def _surface_owner_chain(state, anchors):
    owner = str(anchors[0].owner_id or "")
    colliders = (item for item in state.request.colliders if item.owner_id == owner)
    routes = []
    for collider in colliders:
        routes.extend(_surface_chain_variants(state, collider, anchors))
    return min(routes, key=_segments_length) if routes else None


def _surface_chain_variants(state, collider, anchors):
    points = np.asarray(collider.vertices, dtype=np.float64)
    faces = np.asarray(collider.triangles, dtype=np.int64)
    if not len(points) or not len(faces):
        return ()
    normals, graph, rows = _vertex_normals(points, faces), _mesh_graph(points, faces), []
    for factor in _SURFACE_FACTORS:
        rows.extend(_surface_factor_variants(state, points, normals, graph, anchors, factor))
        if rows:
            break
    return tuple(rows)


def _surface_factor_variants(state, points, normals, graph, anchors, factor):
    routes = []
    for sign in (1.0, -1.0):
        distance = _radius(state) * factor * sign
        offset = points + normals * distance
        lifts = _surface_anchor_lifts(points, normals, anchors, distance)
        result = _surface_chain_variant(state, offset, graph, anchors, lifts)
        if result is not None:
            routes.append(result)
    return tuple(routes)


def _surface_anchor_lifts(points, normals, anchors, distance):
    rows = []
    for anchor in anchors:
        index = int(np.argmin(np.linalg.norm(points - anchor.point, axis=1)))
        rows.append(np.asarray(anchor.point) + normals[index] * distance)
    return tuple(rows)


def _surface_chain_variant(state, points, graph, anchors, lifts):
    output = []
    for index, (start, end) in enumerate(zip(anchors[:-1], anchors[1:])):
        route = _surface_graph_pair(state, points, graph, start, end, lifts[index:index + 2])
        if route is None:
            return None
        output.append(_SegmentRoute(route, V2PlannerMode.SURFACE,
                                    V2PlannerBranch.SURFACE_MESH, str(start.owner_id or "")))
    return tuple(output)


def _surface_graph_pair(state, surface, graph, start, end, lifts):
    points = np.vstack((start.point, end.point, *lifts, surface))
    neighbors = _surface_pair_neighbors(points, graph)
    state.candidate_nodes = max(state.candidate_nodes, len(points))
    route = _search_batched_lazy(state, points, points, neighbors, start.owner_id, end.owner_id)
    if route is None:
        return None
    return _shortcut_route(state, route, start.owner_id, end.owner_id)


def _surface_pair_neighbors(points, graph):
    rows = [set((2,)), set((3,)), set((0,)), set((1,)),
            *(set(value + 4 for value in row) for row in graph)]
    for endpoint in (0, 1):
        lift = endpoint + 2
        nearest = np.argsort(np.linalg.norm(points[4:] - points[lift], axis=1), kind="stable")[:12] + 4
        for node in nearest:
            rows[lift].add(int(node)); rows[int(node)].add(lift)
    return tuple(tuple(sorted(row)) for row in rows)


def _segments_length(routes):
    return sum(_route_length(route.points) for route in routes)


def _shared_chain_candidates(state, anchors):
    rows = [np.asarray(anchor.point) for anchor in anchors]
    for start, end in zip(anchors[:-1], anchors[1:]):
        rows.extend(_compatibility_candidates(state, start, end))
        rows.extend(_roadmap_candidates(state, start, end, True))
    return _dedupe_global(rows)


def _dedupe_global(points):
    output, seen = [], set()
    for point in points:
        value = np.asarray(point, dtype=np.float64); key = tuple(np.round(value, 10))
        if key not in seen:
            seen.add(key); output.append(value)
    return tuple(output)


def _plan_chain_pair(state, start, end, shared):
    if _edge_clear(state, start.point, end.point, start.owner_id, end.owner_id):
        return _direct_segment(start, end)
    surface = _surface_route(state, start, end)
    if surface is not None:
        return surface
    points = _chain_pair_candidates(start, end, shared)
    route = _search_chain_roadmap(state, points, start.owner_id, end.owner_id)
    route = None if route is None else _shortcut_route(state, route, start.owner_id, end.owner_id)
    return _roadmap_segment(route) if route is not None else None


def _chain_pair_candidates(start, end, shared):
    endpoints = (np.asarray(start.point), np.asarray(end.point)); rows = []
    for point in shared:
        if all(np.linalg.norm(point - endpoint) > 1.0e-10 for endpoint in endpoints):
            rows.append(point)
    return (*endpoints, *rows)


def _search_chain_roadmap(state, points, start_owner, end_owner):
    values = np.asarray(points); neighbors = _neighbor_rows_limit(values, 96)
    return _search_batched_lazy(state, points, values, neighbors, start_owner, end_owner)


def _neighbor_rows_limit(points, limit):
    rows, count = [], len(points)
    for index in range(count):
        distances = np.linalg.norm(points - points[index], axis=1)
        order = [int(value) for value in np.argsort(distances, kind="stable") if value != index]
        rows.append(tuple(dict.fromkeys((1, 0, *order[:min(limit, count - 1)]))))
    return tuple(rows)


def _plan_segments_with(state, pair_planner):
    anchors = tuple(state.request.anchors); cyclic = _cyclic(state.request)
    count = len(anchors) if cyclic else len(anchors) - 1
    routes = []
    for index in range(count):
        route = pair_planner(state, anchors[index], anchors[(index + 1) % len(anchors)])
        if route is None:
            return None
        routes.append(route)
    return tuple(routes)


def _plan_pair(state, start, end):
    if _edge_clear(state, start.point, end.point, start.owner_id, end.owner_id):
        return _direct_segment(start, end)
    surface = _surface_route(state, start, end)
    if surface is not None:
        return surface
    route = _roadmap_route(state, start, end)
    return _roadmap_segment(route) if route is not None else None


def _plan_pair_v41(state, start, end):
    if _edge_clear(state, start.point, end.point, start.owner_id, end.owner_id):
        return _direct_segment(start, end)
    owner = str(start.owner_id or "") if start.owner_id == end.owner_id else ""
    surface = _projected_surface_route(state, start, end, owner) if owner else None
    surface = surface or _surface_route(state, start, end)
    if surface is not None:
        return surface
    route = _roadmap_route_v41(state, start, end)
    return _roadmap_segment(route) if route is not None else None


def _direct_segment(start, end):
    owner = str(start.owner_id or "") if start.owner_id == end.owner_id else ""
    return _SegmentRoute((start.point, end.point), V2PlannerMode.DIRECT,
                         V2PlannerBranch.DIRECT, owner)


def _roadmap_segment(points):
    return _SegmentRoute(points, V2PlannerMode.ROADMAP, V2PlannerBranch.ROADMAP)


def _surface_route(state, start, end):
    owner = str(start.owner_id or "")
    if not owner or owner != str(end.owner_id or ""):
        return None
    candidates = [_surface_on_collider(state, item, start, end)
                  for item in state.request.colliders if item.owner_id == owner]
    routes = [route for route in candidates if route is not None]
    return min(routes, key=lambda route: _route_length(route.points)) if routes else None


def _projected_surface_route(state, start, end, owner):
    colliders = tuple(row for row in state.request.colliders if row.owner_id == owner)
    if state.native_world is None or not colliders:
        return None
    world = cached_native_collision_world(colliders)
    samples = _projected_samples(start.point, end.point, _radius(state))
    closest, normals, _distances, _blockers, contained = world.nearest(samples)
    directions = _projection_directions(samples, closest, normals, contained)
    return _best_projected_route(state, start, end, closest, directions)


def _projected_samples(start, end, radius):
    first, second = np.asarray(start), np.asarray(end)
    count = min(32, max(8, int(ceil(np.linalg.norm(second - first) / max(8.0 * radius, 1.0e-6)))))
    factors = np.linspace(0.0, 1.0, count + 1)[1:-1]
    return first + factors[:, None] * (second - first)


def _projection_directions(samples, closest, normals, contained):
    delta = np.asarray(closest) - samples; lengths = np.linalg.norm(delta, axis=1)
    use_delta = np.asarray(contained, dtype=bool) & (lengths > 1.0e-12)
    directions = np.asarray(normals, dtype=np.float64).copy()
    directions[use_delta] = delta[use_delta] / lengths[use_delta, None]
    return directions / np.maximum(np.linalg.norm(directions, axis=1)[:, None], 1.0e-12)


def _best_projected_route(state, start, end, closest, directions):
    for factor in _SURFACE_FACTORS:
        route = _projected_route(state, start, end, closest, directions, factor)
        if _route_clear(state, route, start.owner_id, end.owner_id):
            points = _shortcut_route(state, route, start.owner_id, end.owner_id)
            return _SegmentRoute(points, V2PlannerMode.SURFACE,
                                 V2PlannerBranch.SURFACE_BRIDGE, str(start.owner_id), factor)
    return None


def _projected_route(state, start, end, closest, directions, factor):
    offset = _radius(state) * float(factor)
    rows = [np.asarray(start.point), *(np.asarray(closest) + directions * offset),
            np.asarray(end.point)]
    return _dedupe(rows)


def _surface_on_collider(state, collider, start, end):
    points = np.asarray(collider.vertices, dtype=np.float64)
    faces = np.asarray(collider.triangles, dtype=np.int64)
    if not len(points) or not len(faces):
        return None
    first, last = _nearest_indices(points, start.point, end.point)
    normals = _vertex_normals(points, faces)
    local = _local_surface_bridge(state, start, end, normals[first], normals[last])
    if local is not None:
        route, factor = local
        return _SegmentRoute(route, V2PlannerMode.SURFACE,
                             V2PlannerBranch.SURFACE_BRIDGE, str(start.owner_id), factor)
    return _mesh_surface_segment(state, points, faces, first, last, start, end)


def _mesh_surface_segment(state, points, faces, first, last, start, end):
    indices = _surface_mesh_path(state, points, faces, first, last)
    if not indices:
        return None
    route = _best_offset_route(state, points, faces, indices, start, end)
    return (_SegmentRoute(route, V2PlannerMode.SURFACE, V2PlannerBranch.SURFACE_MESH,
                          str(start.owner_id)) if route is not None else None)


def _surface_mesh_path(state, points, faces, start, goal):
    if state.native_world is None:
        return _mesh_path(points, faces, start, goal)
    path, result = native_mesh_shortest_path(points, faces, start, goal)
    state.native_search_ms += result.search_ms; state.graph_expansions += result.expansions
    state.graph_searches += 1; return tuple(int(value) for value in path)


def _local_surface_bridge(state, start, end, first_normal, last_normal):
    for factor in _SURFACE_FACTORS:
        for sign in (1.0, -1.0):
            route = _bridge_points(state, start.point, end.point, first_normal,
                                   last_normal, factor * sign)
            if _route_clear(state, route, start.owner_id, end.owner_id):
                return _shortcut_route(state, route, start.owner_id, end.owner_id), factor * sign
    return None


def _bridge_points(state, start, end, first_normal, last_normal, factor):
    first, last = np.asarray(start), np.asarray(end)
    distance = float(np.linalg.norm(last - first)); radius = _radius(state)
    count = min(16, max(2, int(ceil(distance / max(4.0 * radius, 1.0e-6)))))
    rows = [first]
    for index in range(count + 1):
        value = index / count; normal = _unit_lerp(first_normal, last_normal, value)
        rows.append(_lerp(first, last, value) + normal * radius * factor)
    rows.append(last)
    return _dedupe(rows)


def _unit_lerp(first, second, factor):
    value = _lerp(first, second, factor)
    return value / max(float(np.linalg.norm(value)), 1.0e-12)


def _nearest_indices(points, start, end):
    first = int(np.argmin(np.sum((points - np.asarray(start)) ** 2, axis=1)))
    last = int(np.argmin(np.sum((points - np.asarray(end)) ** 2, axis=1)))
    return first, last


def _mesh_path(points, faces, start, goal):
    graph = _mesh_graph(points, faces); heap = [(0.0, start)]
    distance, came, seen = {start: 0.0}, {}, set()
    while heap:
        _score, node = heappop(heap)
        if node == goal:
            return _reconstruct(came, goal)
        if node in seen:
            continue
        seen.add(node)
        _expand_mesh_node(points, graph, node, goal, distance, came, heap)
    return ()


def _mesh_graph(points, faces):
    graph = [set() for _point in points]
    for a, b, c in faces:
        graph[a].update((int(b), int(c)))
        graph[b].update((int(a), int(c)))
        graph[c].update((int(a), int(b)))
    return tuple(tuple(sorted(row)) for row in graph)


def _expand_mesh_node(points, graph, node, goal, distance, came, heap):
    for nxt in graph[node]:
        cost = distance[node] + float(np.linalg.norm(points[nxt] - points[node]))
        if cost >= distance.get(nxt, float("inf")):
            continue
        distance[nxt], came[nxt] = cost, node
        score = cost + float(np.linalg.norm(points[nxt] - points[goal]))
        heappush(heap, (score, nxt))


def _reconstruct(came, goal):
    output, node = [goal], goal
    while node in came:
        node = came[node]; output.append(node)
    return tuple(reversed(output))


def _best_offset_route(state, points, faces, indices, start, end):
    normals = _vertex_normals(points, faces)
    rows = []
    for factor in _SURFACE_FACTORS:
        for sign in (1.0, -1.0):
            route = _offset_surface_points(state, points, normals, indices, start, end, factor * sign)
            if _route_clear(state, route, start.owner_id, end.owner_id):
                rows.append(_shortcut_route(state, route, start.owner_id, end.owner_id))
        if rows:
            break
    return min(rows, key=_route_length) if rows else None


def _vertex_normals(points, faces):
    normals = np.zeros_like(points)
    triangles = points[faces]
    face_normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    for column in range(3):
        np.add.at(normals, faces[:, column], face_normals)
    center = points.mean(axis=0); signs = np.sum(normals * (points - center), axis=1)
    normals[signs < 0.0] *= -1.0
    return _normalize_rows(normals, points - center)


def _normalize_rows(values, fallback):
    lengths = np.linalg.norm(values, axis=1)
    fallback_lengths = np.linalg.norm(fallback, axis=1)
    safe = np.where(lengths[:, None] > 1.0e-12, values,
                    fallback / np.maximum(fallback_lengths[:, None], 1.0e-12))
    return safe / np.maximum(np.linalg.norm(safe, axis=1)[:, None], 1.0e-12)


def _offset_surface_points(state, points, normals, indices, start, end, factor):
    radius = _radius(state); offset = radius * factor
    surface = points[np.asarray(indices)] + normals[np.asarray(indices)] * offset
    rows = [np.asarray(start.point), *surface, np.asarray(end.point)]
    return _dedupe(rows)


def _roadmap_route(state, start, end):
    return _roadmap_route_with(state, start, end, _search_compatibility, _search_roadmap)


def _roadmap_route_v41(state, start, end):
    route = _roadmap_route_with(state, start, end, _search_compatibility_v41, _search_roadmap_v41)
    return route if route is not None else _anchor_access_route(state, start, end)


def _anchor_access_route(state, start, end):
    if state.native_world is None: return None
    base = _roadmap_candidates(state, start, end, True); neighbors = _neighbor_rows(np.asarray(base), True)
    for oblique in (False, True):
        exits = anchor_access_candidates(state, start, end, _batch_edge_states, oblique)
        points = append_access_points(base, exits)
        if len(points) == len(base): continue
        graph = append_access_neighbors(points, neighbors, _DENSE_NEIGHBORS)
        graph = _checked_anchor_neighbors(state, points, graph, start, end)
        state.candidate_nodes = max(state.candidate_nodes, len(points))
        route = _search_batched_lazy(state, points, np.asarray(points), graph, start.owner_id, end.owner_id)
        if route is not None and _route_clear(state, route, start.owner_id, end.owner_id):
            return _shortcut_route(state, route, start.owner_id, end.owner_id)
    return None


def _checked_anchor_neighbors(state, points, graph, start, end):
    pairs = sorted({tuple(sorted((i, j))) for i, row in enumerate(graph)
                    for j in row if i != j and (i < 2 or j < 2)})
    owners = tuple(_graph_owners(i, j, start.owner_id, end.owner_id) for i, j in pairs)
    clear = _batch_edge_states(state, np.asarray(points), pairs, owners)
    blocked = {edge for edge, allowed in zip(pairs, clear) if not allowed}
    return tuple(tuple(j for j in row if tuple(sorted((i, j))) not in blocked)
                 for i, row in enumerate(graph))


def _roadmap_route_with(state, start, end, compatibility_search, roadmap_search):
    compatible = _compatibility_candidates(state, start, end)
    state.candidate_nodes = max(state.candidate_nodes, len(compatible))
    route = compatibility_search(state, compatible, start.owner_id, end.owner_id)
    if route is not None:
        return _shortcut_route(state, route, start.owner_id, end.owner_id)
    for dense in (False, True):
        candidates = _roadmap_candidates(state, start, end, dense)
        state.candidate_nodes = max(state.candidate_nodes, len(candidates))
        route = roadmap_search(state, candidates, start.owner_id, end.owner_id, dense)
        if route is not None:
            return _shortcut_route(state, route, start.owner_id, end.owner_id)
    return None


def _search_compatibility(state, points, start_owner, end_owner):
    if len(points) <= 48:
        return _search_complete_roadmap(state, points, start_owner, end_owner)
    return _search_roadmap(state, points, start_owner, end_owner, True)


def _search_compatibility_v41(state, points, start_owner, end_owner):
    values = np.asarray(points)
    neighbors = _complete_neighbors(len(points)) if len(points) <= 48 else _neighbor_rows(values, True)
    return _search_batched_lazy(state, points, values, neighbors, start_owner, end_owner)


def _compatibility_candidates(state, start, end):
    source, target = np.asarray(start.point), np.asarray(end.point)
    active = _active_corridor_colliders(state, source, target)
    colliders = tuple(item for item in active if _single_collider_blocks(state, item, start, end))
    colliders = colliders or active
    rows = [source, target]
    for collider in colliders:
        rows.extend(_compatibility_shell(state, collider))
    return _sample_candidates(_dedupe(rows), _SPARSE_LIMIT)


def _compatibility_shell(state, collider):
    points = np.asarray(collider.vertices, dtype=np.float64)
    if not len(points):
        return ()
    sampled = _sample_rows(points, min(32, len(points)))
    margin = max(_radius(state) * 5.0, state.request.tolerances.numeric_floor)
    return (*_radial_shell(sampled, margin * 4.0), *_bounds_shell(points, margin, False))


def _active_corridor_colliders(state, start, end):
    pad = max(0.05, _radius(state) * 4.0)
    low, high = np.minimum(start, end) - pad, np.maximum(start, end) + pad
    return tuple(item for item in state.request.colliders if _bounds_overlap(item, low, high))


def _bounds_overlap(collider, low, high):
    points = np.asarray(collider.vertices, dtype=np.float64)
    if not len(points):
        return False
    item_low, item_high = points.min(axis=0), points.max(axis=0)
    return bool(np.all(high >= item_low) and np.all(item_high >= low))


def _single_collider_blocks(state, collider, start, end):
    if state.native_world is not None:
        return _native_collider_blocks(state, collider, start, end)
    snapshot = build_triangle_snapshot((collider,))
    points = np.asarray((start.point, end.point), dtype=np.float64)
    contacts = _endpoint_contacts(points, start.owner_id, end.owner_id, _radius(state))
    result = validate_static_clearance(points, snapshot, _radius(state), contacts,
                                       slack=_slack(state))
    return not result.valid


def _native_collider_blocks(state, collider, start, end):
    index = state.native_world.collider_ids.index(collider.collider_id)
    points = np.asarray((start.point, end.point), dtype=np.float64)
    owners = ((start.owner_id, end.owner_id),)
    result = state.native_world.validate_instance(index, points, ((0, 1),), owners,
                                                  _state_contact_span(state),
                                                  _radius(state) - _slack(state))
    return not result.clear[0]


def _sample_candidates(points, limit):
    if len(points) <= limit:
        return tuple(points)
    return (points[0], points[1], *_sample_rows(np.asarray(points[2:]), limit - 2))


def _sample_rows(points, count):
    indices = np.linspace(0, len(points) - 1, count).round().astype(np.int64)
    return tuple(points[index] for index in indices)


def _radial_shell(points, pad):
    center = np.asarray(points).mean(axis=0); rows = []
    for point in points:
        delta = point - center; length = max(float(np.linalg.norm(delta)), 1.0e-12)
        rows.append(point + delta * (pad / length))
    return tuple(rows)


def _roadmap_candidates(state, start, end, dense):
    source, target = np.asarray(start.point), np.asarray(end.point)
    colliders = _corridor_colliders(state.request.colliders, source, target, dense)
    groups = [_collider_shell(state, collider, source, target, dense)
              for collider in colliders]
    limit = _DENSE_LIMIT if dense else _SPARSE_LIMIT
    return _grouped_candidates(groups, source, target, limit, dense)


def _corridor_colliders(colliders, start, end, dense):
    rows = sorted((( _collider_line_distance(item, start, end), item.collider_id, item)
                   for item in colliders), key=lambda row: (row[0], row[1]))
    length = float(np.linalg.norm(end - start)); threshold = max(0.05, length * 0.3)
    nearby = [item for distance, _identifier, item in rows if distance <= threshold]
    limit = 16 if dense else 8
    return tuple((nearby or [row[2] for row in rows[:limit]])[:limit])


def _collider_line_distance(collider, start, end):
    points = np.asarray(collider.vertices, dtype=np.float64)
    low, high = points.min(axis=0), points.max(axis=0)
    factors = np.linspace(0.0, 1.0, 33)
    samples = start + factors[:, None] * (end - start)
    nearest = np.minimum(np.maximum(samples, low), high)
    return float(np.min(np.linalg.norm(samples - nearest, axis=1)))


def _grouped_candidates(groups, start, end, limit, dense):
    if not groups:
        return (start, end)
    quota = max(1, (limit - 2) // len(groups)); selected, remainder = [], []
    for group in groups:
        rows = list(_dedupe(group))
        chosen = tuple(rows[:quota]) if dense else _group_quota(rows, start, end, quota)
        selected.extend(chosen)
        remainder.extend(row for row in rows if not _contains_point(chosen, row))
    output = list(_dedupe((start, end, *selected)))
    if len(output) < limit:
        output.extend(_ranked_points(remainder, start, end, limit - len(output)))
    return tuple(_dedupe(output[:limit]))


def _group_quota(rows, start, end, quota):
    bounds = rows[:min(14, len(rows))]; mesh = rows[min(14, len(rows)):]
    bound_count = min(len(bounds), max(1, quota // 4))
    first = _ranked_points(bounds, start, end, bound_count)
    second = _ranked_points(mesh, start, end, max(0, quota - len(first)))
    return tuple((*first, *second))


def _contains_point(points, target):
    return any(np.linalg.norm(np.asarray(point) - target) <= 1.0e-10 for point in points)


def _ranked_points(points, start, end, limit):
    rows = _dedupe(points)
    if not rows or limit <= 0:
        return ()
    values = np.asarray(rows); scores = _line_distance_rows(values, start, end)
    order = np.argsort(scores, kind="stable")[:limit]
    return tuple(rows[int(index)] for index in order)


def _collider_shell(state, collider, start, end, dense):
    points = np.asarray(collider.vertices, dtype=np.float64)
    faces = np.asarray(collider.triangles, dtype=np.int64)
    if not len(points) or not len(faces):
        return ()
    radius = _radius(state); scale = state.request.tolerances.length_scale
    bounds = _bounds_shell(points, max(radius * 4.0, scale * 0.00025), dense)
    mesh = _mesh_shell(points, faces, start, end, max(radius * 8.0, scale * 0.001), dense)
    return (*bounds, *mesh)


def _bounds_shell(points, pad, dense):
    low, high = points.min(axis=0) - pad, points.max(axis=0) + pad
    center = (low + high) * 0.5
    corners = [np.asarray((x, y, z)) for x in (low[0], high[0])
               for y in (low[1], high[1]) for z in (low[2], high[2])]
    faces = [center + np.eye(3)[axis] * sign * (high[axis] - low[axis]) * 0.5
             for axis in range(3) for sign in (-1.0, 1.0)]
    return tuple(corners + faces + (_edge_shell(low, high) if dense else []))


def _edge_shell(low, high):
    center = (low + high) * 0.5; rows = []
    for free in range(3):
        fixed = [axis for axis in range(3) if axis != free]
        for first in (low[fixed[0]], high[fixed[0]]):
            for second in (low[fixed[1]], high[fixed[1]]):
                point = center.copy(); point[fixed] = (first, second); rows.append(point)
    return rows


def _mesh_shell(points, faces, start, end, pad, dense):
    triangles = points[faces]; centers = triangles.mean(axis=1)
    normals = _face_normals(points, triangles)
    distances = _line_distance_rows(centers, start, end)
    limit = 48 if dense else 20
    indices = np.argsort(distances, kind="stable")[:min(limit, len(faces))]
    signs = (1.0, -1.0) if dense else (1.0,)
    face_rows = tuple(centers[index] + sign * pad * normals[index]
                      for index in indices for sign in signs)
    return (*_vertex_shell(points, start, end, pad, dense), *face_rows)


def _vertex_shell(points, start, end, pad, dense):
    _ = start, end
    limit = min(len(points), 96 if dense else 32); center = points.mean(axis=0)
    indices = tuple(map(int, np.linspace(0, len(points) - 1, limit).round()))
    rows = []
    for index in indices:
        direction = points[index] - center; length = float(np.linalg.norm(direction))
        rows.append(points[index] + direction * (max(pad, 1.0e-6) / max(length, 1.0e-12)))
    return tuple(rows)


def _face_normals(points, triangles):
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    center = points.mean(axis=0); signs = np.sum(normals * (triangles.mean(axis=1) - center), axis=1)
    normals[signs < 0.0] *= -1.0
    lengths = np.linalg.norm(normals, axis=1)
    return normals / np.maximum(lengths[:, None], 1.0e-12)


def _line_distance_rows(points, start, end):
    delta = end - start; denom = float(np.dot(delta, delta))
    if denom <= 1.0e-24:
        return np.linalg.norm(points - start, axis=1)
    factors = np.clip(((points - start) @ delta) / denom, 0.0, 1.0)
    return np.linalg.norm(points - (start + factors[:, None] * delta), axis=1)


def _search_roadmap(state, points, start_owner, end_owner, dense):
    values = np.asarray(points); neighbors = _neighbor_rows(values, dense)
    if len(points) <= 48:
        return _eager_roadmap_path(state, points, values, neighbors, start_owner, end_owner)
    invalid, validated = set(), set()
    for _attempt in range(512 if dense else 256):
        state.graph_searches += 1
        path = _geometric_path(values, neighbors, invalid)
        if path is None:
            return None
        edges = tuple(tuple(sorted(edge)) for edge in zip(path[:-1], path[1:]))
        _validate_lazy_edges(state, values, edges, validated, invalid, start_owner, end_owner)
        if all(edge in validated for edge in edges):
            return tuple(points[index] for index in path)
    return None


def _search_complete_roadmap(state, points, start_owner, end_owner):
    values = np.asarray(points); neighbors = _complete_neighbors(len(points))
    invalid, validated = set(), set()
    for _attempt in range(512):
        state.graph_searches += 1
        path = _geometric_path(values, neighbors, invalid)
        if path is None:
            return None
        edges = tuple(tuple(sorted(edge)) for edge in zip(path[:-1], path[1:]))
        _validate_lazy_edges(state, values, edges, validated, invalid, start_owner, end_owner)
        if all(edge in validated for edge in edges):
            return tuple(points[index] for index in path)
    return None


def _eager_roadmap_path(state, points, values, neighbors, start_owner, end_owner):
    pairs = sorted({tuple(sorted((index, nxt))) for index, row in enumerate(neighbors)
                    for nxt in row if index != nxt})
    owners = tuple(_graph_owners(a, b, start_owner, end_owner) for a, b in pairs)
    clear = _batch_edge_states(state, values, pairs, owners); graph = [[] for _point in points]
    for (first, second), allowed in zip(pairs, clear):
        if allowed:
            graph[first].append(second); graph[second].append(first)
    state.graph_searches += 1; path = _geometric_path(values, graph, set())
    return None if path is None else tuple(points[index] for index in path)


def _search_roadmap_v41(state, points, start_owner, end_owner, dense):
    values = np.asarray(points); neighbors = _neighbor_rows(values, dense)
    return _search_batched_lazy(state, points, values, neighbors, start_owner, end_owner)


def _search_batched_lazy(state, points, values, neighbors, start_owner, end_owner):
    if state.native_world is not None:
        return _search_native_lazy(state, points, values, neighbors, start_owner, end_owner)
    invalid, validated = set(), set(); metric = _graph_metric(values)
    state.graph_metric_builds += 1
    for _attempt in range(512):
        state.graph_searches += 1; path = _geometric_path_metric(metric, neighbors, invalid, state)
        if path is None:
            return None
        edges = tuple(tuple(sorted(edge)) for edge in zip(path[:-1], path[1:]))
        _validate_lazy_edges(state, values, edges, validated, invalid, start_owner, end_owner)
        if all(edge in validated for edge in edges):
            return tuple(points[index] for index in path)
    return None


def _search_native_lazy(state, points, values, neighbors, start_owner, end_owner):
    path, result = state.native_world.lazy_path(values, neighbors, start_owner, end_owner,
                                                _state_contact_span(state),
                                                _radius(state) - _slack(state))
    _absorb_native_search(state, result)
    return None if result.status or not len(path) else tuple(points[int(index)] for index in path)


def _absorb_native_search(state, result):
    state.graph_metric_builds += 1; state.graph_searches += result.searches
    state.graph_expansions += result.expansions; state.tested_edges += result.validated + result.rejected
    state.rejected_edges += result.rejected; state.candidate_pairs += result.candidates
    state.tested_pairs += result.tested; state.edge_batches += result.searches
    state.native_search_ms += result.search_ms; state.native_collision_ms += result.collision_ms


def _complete_neighbors(count):
    return tuple(tuple(other for other in range(count) if other != index)
                 for index in range(count))


def _validate_lazy_edges(state, points, edges, validated, invalid, start_owner, end_owner):
    pending = tuple(edge for edge in edges if edge not in validated and edge not in invalid)
    if not pending:
        return
    owners = tuple(_graph_owners(a, b, start_owner, end_owner) for a, b in pending)
    clear = _batch_edge_states(state, points, pending, owners)
    for edge, allowed in zip(pending, clear):
        (validated if allowed else invalid).add(edge)


def _geometric_path(points, neighbors, invalid):
    heap, distance, came, seen = [(0.0, 0)], {0: 0.0}, {}, set()
    while heap:
        _score, node = heappop(heap)
        if node == 1:
            return _reconstruct(came, 1)
        if node in seen:
            continue
        seen.add(node)
        _expand_geometric(points, neighbors[node], node, invalid, distance, came, heap)
    return None


def _graph_metric(points):
    delta = points[:, None, :] - points[None, :, :]
    return np.linalg.norm(delta, axis=2)


def _geometric_path_metric(metric, neighbors, invalid, state=None):
    heap, distance, came, seen = [(0.0, 0)], {0: 0.0}, {}, set()
    while heap:
        _score, node = heappop(heap)
        if node == 1:
            return _reconstruct(came, 1)
        if node not in seen:
            if state is not None:
                state.graph_expansions += 1
            seen.add(node); _expand_metric(metric, neighbors[node], node, invalid, distance, came, heap)
    return None


def _expand_metric(metric, neighbors, node, invalid, distance, came, heap):
    for nxt in neighbors:
        if tuple(sorted((node, nxt))) in invalid:
            continue
        cost = distance[node] + float(metric[node, nxt])
        if cost < distance.get(nxt, float("inf")):
            distance[nxt], came[nxt] = cost, node
            heappush(heap, (cost + float(metric[nxt, 1]), nxt))


def _expand_geometric(points, neighbors, node, invalid, distance, came, heap):
    for nxt in neighbors:
        if tuple(sorted((node, nxt))) in invalid:
            continue
        cost = distance[node] + float(np.linalg.norm(points[nxt] - points[node]))
        if cost >= distance.get(nxt, float("inf")):
            continue
        distance[nxt], came[nxt] = cost, node
        heappush(heap, (cost + float(np.linalg.norm(points[nxt] - points[1])), nxt))


def _neighbor_rows(points, dense):
    count = len(points); limit = _DENSE_NEIGHBORS if dense else _SPARSE_NEIGHBORS
    rows = []
    for index in range(count):
        distances = np.linalg.norm(points - points[index], axis=1)
        order = [int(value) for value in np.argsort(distances, kind="stable") if value != index]
        rows.append(tuple(dict.fromkeys((1, 0, *order[:min(limit, count - 1)]))))
    return tuple(rows)


def _graph_owners(first, second, start_owner, end_owner):
    return (start_owner if first == 0 else end_owner if first == 1 else "",
            start_owner if second == 0 else end_owner if second == 1 else "")


def _shortcut_route(state, points, start_owner, end_owner):
    route = tuple(np.asarray(point) for point in points)
    output, index = [route[0]], 0
    while index < len(route) - 1:
        index = _furthest_clear(state, route, index, start_owner, end_owner)
        output.append(route[index])
    return tuple(output)


def _furthest_clear(state, route, index, start_owner, end_owner):
    candidates = tuple(range(index + 1, len(route)))
    edges = tuple((index, candidate) for candidate in candidates)
    owners = tuple((start_owner if index == 0 else "",
                    end_owner if candidate == len(route) - 1 else "") for candidate in candidates)
    clear = _batch_edge_states(state, np.asarray(route), edges, owners)
    for candidate, allowed in reversed(tuple(zip(candidates, clear))):
        if allowed:
            return candidate
    return index + 1


def _route_clear(state, points, start_owner, end_owner):
    edges = tuple((index, index + 1) for index in range(len(points) - 1))
    owners = tuple((start_owner if index == 0 else "",
                    end_owner if index + 2 == len(points) else "") for index in range(len(edges)))
    return all(_batch_edge_states(state, np.asarray(points), edges, owners))


def _batch_edge_states(state, points, edges, owners):
    if state.native_world is not None:
        return _native_edge_states(state, points, edges, owners)
    result = validate_segment_clearance_batch(points, edges, state.snapshot, _radius(state),
                                              owners, _state_contact_span(state),
                                              _slack(state), containment_cache=state.membership_cache)
    state.tested_edges += len(edges)
    state.edge_batches += int(bool(len(edges)))
    state.rejected_edges += sum(not value for value in result.clear)
    state.candidate_pairs += result.candidate_pairs; state.tested_pairs += result.tested_pairs
    _store_edge_states(state, points, edges, owners, result.clear)
    return result.clear


def _native_edge_states(state, points, edges, owners):
    started = perf_counter()
    result = validate_native_owner_chords(state.request, state.native_world, points, edges, owners,
                                          _state_contact_span(state), _radius(state) - _slack(state))
    state.native_collision_ms += 1000.0 * (perf_counter() - started)
    state.tested_edges += len(edges); state.edge_batches += int(bool(len(edges)))
    state.rejected_edges += sum(not value for value in result.clear)
    state.candidate_pairs += result.candidate_pairs; state.tested_pairs += result.tested_pairs
    _store_edge_states(state, points, edges, owners, result.clear)
    return result.clear


def validate_native_owner_chords(request, world, points, edges, owners, span, threshold):
    result = world.validate(points, edges, owners, span, threshold)
    return guard_native_owner_chords(request, world, points, edges, owners, span, threshold, result)


def guard_native_owner_chords(request, world, points, edges, owners, span, threshold, result):
    probes, rows = _owner_chord_probes(points, edges, owners, span, threshold, result.clear)
    failures = _owner_probe_failures(world, probes, rows, _collider_owner_map(request))
    return _reject_owner_chords(result, failures)


def _collider_owner_map(request):
    return {item.collider_id: item.owner_id for item in request.colliders}


def _owner_chord_probes(points, edges, owners, span, threshold, clear):
    values, probes, rows = np.asarray(points, dtype=np.float64), [], []
    for edge_index, (edge, owner) in enumerate(zip(edges, owners)):
        if clear[edge_index]:
            _append_owner_probes(values[np.asarray(edge, dtype=np.int64)], owner, span,
                                 threshold, edge_index, probes, rows)
    return np.asarray(probes, dtype=np.float64).reshape((-1, 3)), tuple(rows)


def _append_owner_probes(edge, owners, span, threshold, index, probes, rows):
    length = float(np.linalg.norm(edge[1] - edge[0]))
    low = float(span) / max(length, 1.0e-12) if owners[0] else 0.0
    high = 1.0 - float(span) / max(length, 1.0e-12) if owners[1] else 1.0
    if low >= high:
        return
    offset = min((high - low) * .1, max(1.0e-9, float(threshold) / max(length, 1.0e-12)))
    _append_owner_probe(edge, low + offset, owners[0], index, probes, rows)
    _append_owner_probe(edge, high - offset, owners[1], index, probes, rows)


def _append_owner_probe(edge, factor, owner, index, probes, rows):
    if owner:
        probes.append(edge[0] + float(factor) * (edge[1] - edge[0]))
        rows.append((int(index), str(owner)))


def _owner_probe_failures(world, probes, rows, owner_map):
    if not len(probes):
        return ()
    _closest, _normals, _distances, blockers, contained = world.nearest(probes)
    return tuple((edge, blocker) for (edge, owner), blocker, inside in zip(rows, blockers, contained)
                 if inside and owner_map.get(str(blocker or ""), "") == owner)


def _reject_owner_chords(result, failures):
    if not failures:
        return result
    clear, blockers = list(result.clear), list(result.blockers or ("",) * len(result.clear))
    for edge, blocker in failures:
        clear[edge], blockers[edge] = False, str(blocker or "")
    contained = tuple(dict.fromkeys((*result.contained_endpoints, *failures)))
    return replace(result, clear=tuple(clear), blockers=tuple(blockers),
                   contained_endpoints=contained)


def _store_edge_states(state, points, edges, owners, values):
    for (first, second), owner, value in zip(edges, owners, values):
        key = _edge_key(points[first], points[second], owner[0], owner[1])
        state.edge_cache[key] = bool(value)


def _edge_clear(state, start, end, start_owner="", end_owner=""):
    key = _edge_key(start, end, start_owner, end_owner)
    if key in state.edge_cache:
        return state.edge_cache[key]
    if state.native_world is not None:
        return _batch_edge_states(state, np.asarray((start, end)), ((0, 1),),
                                  ((start_owner, end_owner),))[0]
    points = np.asarray((start, end), dtype=np.float64)
    contacts = _endpoint_contacts(points, start_owner, end_owner, _radius(state))
    result = validate_static_clearance(points, state.snapshot, _radius(state), contacts,
                                       slack=_slack(state))
    state.tested_edges += 1; state.rejected_edges += int(not result.valid)
    state.edge_cache[key] = bool(result.valid)
    return bool(result.valid)


def _edge_key(start, end, start_owner, end_owner):
    first = tuple(np.round(np.asarray(start, dtype=np.float64), 12))
    second = tuple(np.round(np.asarray(end, dtype=np.float64), 12))
    return first, second, str(start_owner or ""), str(end_owner or "")


def _endpoint_contacts(points, start_owner, end_owner, radius):
    length = float(np.linalg.norm(points[1] - points[0])); span = _contact_span(radius)
    rows = []
    if start_owner:
        rows.append(V2OwnerContact(start_owner, (0,), ((0, 0.0, min(1.0, span / max(length, 1e-12))),)))
    if end_owner:
        rows.append(V2OwnerContact(end_owner, (1,), ((0, max(0.0, 1.0 - span / max(length, 1e-12)), 1.0),)))
    return tuple(rows)


def _finish_plan(state, routes, started):
    if routes is None:
        return _failed_with_state(state, V2Termination.NO_FEASIBLE_PATH,
                                  "no collision-free route joins all anchors", started)
    handoff_started = perf_counter(); handoff = _exact_handoff(state, routes)
    if handoff is None:
        return _failed_with_state(state, V2Termination.NO_FEASIBLE_PATH,
                                  "safe corridor cannot fit requested node count", started)
    return _validated_result(state, routes, handoff, started, handoff_started)


def _failed_with_state(state, reason, message, started):
    diag = _diagnostics(state, (), started, 0.0, None)
    return V2PlannerResult(reason, V2PlannerMode.DIRECT, diagnostics=diag, message=message)


def _exact_handoff(state, routes):
    cyclic = _cyclic(state.request); edge_budget = state.request.settings.node_count - int(not cyclic)
    corridor_edges = sum(len(route.points) - 1 for route in routes)
    if corridor_edges > edge_budget:
        routes = _reduce_routes(state, routes, edge_budget)
    if routes is None:
        return None
    allocations = _edge_allocations(routes, edge_budget)
    return _subdivide_routes(routes, allocations, cyclic)


def _reduce_routes(state, routes, edge_budget):
    rows = list(routes)
    while sum(len(row.points) - 1 for row in rows) > edge_budget:
        candidate = _best_route_removal(state, rows)
        if candidate is None:
            return None
        route, index = candidate; points = list(rows[route].points)
        del points[index]; rows[route] = replace(rows[route], points=tuple(points))
    return tuple(rows)


def _best_route_removal(state, routes):
    candidates = []
    for route_index, route in enumerate(routes):
        for index in range(1, len(route.points) - 1):
            if _edge_clear(state, route.points[index - 1], route.points[index + 1]):
                cost = _removal_cost(route.points, index)
                candidates.append((cost, route_index, index))
    return None if not candidates else min(candidates)[1:]


def _removal_cost(points, index):
    before = np.linalg.norm(np.asarray(points[index]) - points[index - 1])
    before += np.linalg.norm(np.asarray(points[index + 1]) - points[index])
    after = np.linalg.norm(np.asarray(points[index + 1]) - points[index - 1])
    return float(before - after)


def _edge_allocations(routes, edge_budget):
    lengths = np.asarray([np.linalg.norm(np.asarray(b) - a) for route in routes
                          for a, b in zip(route.points[:-1], route.points[1:])])
    counts = np.ones(len(lengths), dtype=np.int64); remaining = edge_budget - len(counts)
    if remaining <= 0:
        return tuple(int(value) for value in counts)
    weights = lengths / max(float(lengths.sum()), 1.0e-12); raw = weights * remaining
    counts += np.floor(raw).astype(np.int64); left = remaining - int(np.floor(raw).sum())
    order = np.argsort(-(raw - np.floor(raw)), kind="stable")
    counts[order[:left]] += 1
    return tuple(int(value) for value in counts)


def _subdivide_routes(routes, allocations, cyclic):
    points, pins, spans, allocation_index, edge_index = [], [0], [], 0, 0
    for anchor_index, route in enumerate(routes):
        first_edge = edge_index
        for start, end in zip(route.points[:-1], route.points[1:]):
            count = allocations[allocation_index]; allocation_index += 1
            if not points:
                points.append(tuple(start))
            points.extend(tuple(_lerp(start, end, step / count)) for step in range(1, count + 1))
            edge_index += count
        spans.append(_planner_span(route, first_edge, edge_index, anchor_index, len(routes), cyclic))
        pins.append(edge_index)
    if cyclic:
        points.pop(); pins.pop()
    return tuple(points), tuple(pins), tuple(spans)


def _planner_span(route, first, last, anchor, count, cyclic):
    end_anchor = (anchor + 1) % count if cyclic else anchor + 1
    return V2PlannerSpan(first, last - first, route.branch, route.owner_id,
                         route.lift_factor, anchor, end_anchor)


def _validated_result(state, routes, handoff, started, handoff_started):
    reference, pins, spans = handoff; contacts = _authored_contacts(state, reference, pins)
    result = validate_static_clearance(reference, state.snapshot, _radius(state), contacts,
                                       cyclic=_cyclic(state.request), slack=_slack(state))
    if not result.valid:
        return _failed_with_state(state, V2Termination.NO_FEASIBLE_PATH,
                                  "exact-count handoff failed independent validation", started)
    corridor = _merged_corridor(routes, _cyclic(state.request)); mode = _merged_mode(routes)
    diag = _diagnostics(state, corridor, started, handoff_started, result)
    ids = tuple(item.collider_id for item in state.request.colliders)
    return V2PlannerResult(V2Termination.CONVERGED, mode, reference, corridor,
                           pins, contacts, ids, diag, spans=spans)


def _authored_contacts(state, points, pins):
    rows = []
    for anchor, index in zip(state.request.anchors, pins):
        if anchor.owner_id:
            rows.append(_anchor_contact(points, int(index), anchor.owner_id,
                                        _state_contact_span(state), _cyclic(state.request)))
    return tuple(rows)


def _anchor_contact(points, index, owner, span, cyclic):
    node_indices = {index}; intervals = []
    for direction in (-1, 1):
        _walk_contact(points, index, direction, span, cyclic, node_indices, intervals)
    return V2OwnerContact(owner, tuple(sorted(node_indices)), tuple(sorted(intervals)))


def _walk_contact(points, index, direction, span, cyclic, nodes, intervals):
    count, travelled, node = len(points), 0.0, index
    for _step in range(count - 1):
        nxt = node + direction
        if not cyclic and not 0 <= nxt < count:
            break
        nxt %= count; edge = nxt if direction < 0 else node
        length = float(np.linalg.norm(np.asarray(points[nxt]) - points[node]))
        fraction = min(1.0, max(0.0, (span - travelled) / max(length, 1.0e-12)))
        _append_contact_interval(intervals, edge, direction, fraction)
        if travelled + length > span:
            break
        nodes.add(nxt); travelled += length; node = nxt


def _append_contact_interval(intervals, edge, direction, fraction):
    if fraction <= 0.0:
        return
    if direction < 0:
        intervals.append((edge, 1.0 - fraction, 1.0))
    else:
        intervals.append((edge, 0.0, fraction))


def _merged_corridor(routes, cyclic):
    output = []
    for index, route in enumerate(routes):
        output.extend(route.points[1:] if index else route.points)
    if cyclic and output and np.allclose(output[0], output[-1]):
        output.pop()
    return tuple(tuple(point) for point in output)


def _merged_mode(routes):
    modes = {route.mode for route in routes}
    if V2PlannerMode.ROADMAP in modes:
        return V2PlannerMode.ROADMAP
    return V2PlannerMode.SURFACE if V2PlannerMode.SURFACE in modes else V2PlannerMode.DIRECT


def _diagnostics(state, corridor, started, handoff_started, validation):
    planner_ms = 1000.0 * ((handoff_started or perf_counter()) - started)
    handoff_ms = 0.0 if not handoff_started else 1000.0 * (perf_counter() - handoff_started)
    pairs = state.candidate_pairs + (0 if validation is None else validation.candidate_pairs)
    tested = state.tested_pairs + (0 if validation is None else validation.tested_pairs)
    return V2PlannerDiagnostics(state.candidate_nodes, state.tested_edges,
                                state.rejected_edges, len(corridor), pairs, tested,
                                planner_ms, handoff_ms, state.graph_searches,
                                state.edge_batches, state.frontier_edges,
                                state.graph_metric_builds, state.graph_expansions,
                                state.chain_groups, state.shared_candidates,
                                state.native_search_ms, state.native_collision_ms)


def _route_length(points):
    return sum(float(np.linalg.norm(np.asarray(b) - a)) for a, b in zip(points[:-1], points[1:]))


def _dedupe(points, tolerance=1.0e-10):
    output = []
    for point in points:
        value = np.asarray(point, dtype=np.float64)
        if not output or np.linalg.norm(value - output[-1]) > tolerance:
            output.append(value)
    return tuple(output)


def _lerp(start, end, factor):
    first, second = np.asarray(start), np.asarray(end)
    return first + float(factor) * (second - first)


def _contact_span(radius):
    return max(2.5 * float(radius), 1.0e-7)


def _state_contact_span(state):
    return max(state.owner_contact_factor * _radius(state), 1.0e-7)


def _radius(state):
    return float(state.request.collision_policy.collision_radius)


def _slack(state):
    return float(state.request.tolerances.clearance_slack)


def _cyclic(request):
    return request.settings.topology is V2Topology.CYCLIC
