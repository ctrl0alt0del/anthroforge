"""Bounded, collision-checked connections from surface anchors to a roadmap."""

import numpy as np

from .collision import cached_native_collision_world


def anchor_access_candidates(state, start, end, validate, oblique=False):
    rows = []
    for anchor in (start, end):
        candidates = _anchor_candidates(state, anchor, oblique)
        rows.extend(_validated_candidates(state, anchor, candidates, validate))
    return tuple(rows)


def _anchor_candidates(state, anchor, oblique):
    colliders = tuple(row for row in state.request.colliders if row.owner_id == anchor.owner_id)
    if not anchor.owner_id or not colliders: return ()
    world = cached_native_collision_world(colliders)
    _closest, normals, _distance, _blockers, _inside = world.nearest(np.asarray([anchor.point]))
    normal = np.asarray(normals[0], dtype=np.float64); length = np.linalg.norm(normal)
    if not np.all(np.isfinite(normal)) or length <= 1.0e-12: return ()
    tolerance = state.request.tolerances; radius = state.request.collision_policy.collision_radius
    scale = max(radius, 4.0 * tolerance.clearance_slack, tolerance.numeric_floor, 1.0e-7)
    return tuple(np.asarray(anchor.point) + direction * scale * factor
                 for direction in _exit_directions(normal / length, oblique) for factor in (2.0, 4.0))


def _exit_directions(normal, oblique):
    if not oblique: return (normal,)
    axis = np.eye(3)[int(np.argmin(np.abs(normal)))]; tangent = np.cross(normal, axis)
    tangent /= np.linalg.norm(tangent); bitangent = np.cross(normal, tangent)
    directions = [normal, -normal]
    for side in (normal, -normal):
        directions.extend((side + tangent, side - tangent, side + bitangent, side - bitangent))
    return tuple(row / np.linalg.norm(row) for row in directions)


def _validated_candidates(state, anchor, candidates, validate):
    if not candidates: return ()
    points = np.asarray((anchor.point, *candidates), dtype=np.float64)
    edges = tuple((0, index) for index in range(1, len(points)))
    owners = ((anchor.owner_id, ""),) * len(edges)
    clear = validate(state, points, edges, owners)
    nodes = tuple((index, index) for index in range(1, len(points)))
    free = validate(state, points, nodes, (("", ""),) * len(nodes))
    return tuple(point for point, edge_clear, node_clear in zip(candidates, clear, free) if edge_clear and node_clear)


def append_access_points(points, candidates):
    """Keep original indices, including coincident vertices on different surfaces."""
    rows = list(points); seen = {_point_key(point) for point in rows}
    for point in candidates:
        key = _point_key(point)
        if key not in seen: rows.append(point); seen.add(key)
    return tuple(rows)


def _point_key(point):
    return tuple(np.round(np.asarray(point, dtype=np.float64), 10))


def append_access_neighbors(points, original, limit=48):
    """Add local connections without replacing any pre-existing graph edge."""
    values = np.asarray(points); rows = [set(row) for row in original]
    rows.extend(set() for _index in range(len(values) - len(rows)))
    for index in range(len(original), len(values)):
        order = np.argsort(np.linalg.norm(values - values[index], axis=1), kind="stable")
        nearest = [int(other) for other in order if other != index][:limit]
        for other in dict.fromkeys((0, 1, *nearest)):
            rows[index].add(other); rows[other].add(index)
    return tuple(tuple(sorted(row)) for row in rows)
