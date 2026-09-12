"""Temporary disk mesh for a region; persistent ownership remains vertex-bound."""
from collections import Counter
import numpy as np
from .errors import require


def mesh(polygons):
    require(bool(polygons), 'REGION_EMPTY')
    require(len(polygons) <= 8192 and sum(map(len, polygons)) <= 25000, 'LAYOUT_PATCH_BUDGET')
    points = np.concatenate(polygons)
    scale = float(np.linalg.norm(np.ptp(points, axis=0)))
    require(scale > 1e-10, 'LAYOUT_DEGENERATE_PATCH')
    vertices, lookup, rings = [], {}, []
    for polygon in polygons:
        rings.append(weld(polygon, vertices, lookup, points.min(axis=0), scale * 1e-9))
    counts = Counter(edge for ring in rings for edge in edges(ring))
    require(max(counts.values()) <= 2, 'LAYOUT_NONMANIFOLD_PATCH')
    faces = triangulate(vertices, rings, counts)
    require(len(vertices) <= 8192 and len(faces) <= 20000, 'LAYOUT_PATCH_BUDGET')
    boundary = disk_boundary(len(vertices), faces)
    return dict(vertices=np.asarray(vertices), faces=np.asarray(faces, dtype=int), boundary=boundary, scale=scale)


def weld(polygon, vertices, lookup, origin, epsilon):
    ring = []
    for point in polygon:
        key = tuple(np.rint((np.asarray(point)-origin)/epsilon).astype(np.int64))
        if key not in lookup:
            lookup[key] = len(vertices)
            vertices.append(np.asarray(point, dtype=float))
        if not ring or ring[-1] != lookup[key]:
            ring.append(lookup[key])
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    require(len(ring) >= 3 and len(set(ring)) == len(ring), 'LAYOUT_DEGENERATE_PATCH')
    return ring


def edges(ring):
    return [tuple(sorted(pair)) for pair in zip(ring, ring[1:]+ring[:1])]


def triangulate(vertices, rings, counts):
    midpoints, faces = {}, []
    for edge, count in counts.items():
        if count == 2:
            midpoints[edge] = len(vertices)
            vertices.append((vertices[edge[0]]+vertices[edge[1]])/2)
    for ring in rings:
        expanded = expand_ring(ring, midpoints)
        center = len(vertices)
        vertices.append(np.mean([vertices[i] for i in ring], axis=0))
        faces.extend((a, b, center) for a, b in zip(expanded, expanded[1:]+expanded[:1]))
    return faces


def expand_ring(ring, midpoints):
    expanded = []
    for a, b in zip(ring, ring[1:]+ring[:1]):
        expanded.append(a)
        if tuple(sorted((a, b))) in midpoints:
            expanded.append(midpoints[tuple(sorted((a, b)))])
    return expanded


def disk_boundary(count, faces):
    counts = Counter(edge for face in faces for edge in edges(list(face)))
    require(max(counts.values()) <= 2, 'LAYOUT_NONMANIFOLD_PATCH')
    require(count-len(counts)+len(faces) == 1, 'LAYOUT_REQUIRES_DISK', 'Use one connected area without holes.')
    neighbors = {}
    for (a, b), uses in counts.items():
        if uses == 1:
            neighbors.setdefault(a, []).append(b)
            neighbors.setdefault(b, []).append(a)
    require(bool(neighbors) and all(len(v) == 2 for v in neighbors.values()), 'LAYOUT_REQUIRES_DISK')
    boundary = walk_boundary(neighbors)
    require(len(boundary) == len(neighbors), 'LAYOUT_REQUIRES_DISK', 'The area has multiple boundary loops.')
    connected(count, counts)
    return np.asarray(boundary, dtype=int)


def walk_boundary(neighbors):
    path = [min(neighbors)]
    previous, current = -1, path[0]
    for _ in range(len(neighbors)):
        following = next(v for v in neighbors[current] if v != previous)
        if following == path[0]:
            return path
        path.append(following)
        previous, current = current, following
    require(False, 'LAYOUT_REQUIRES_DISK')


def connected(count, edges_by_use):
    neighbors = [set() for _ in range(count)]
    for a, b in edges_by_use:
        neighbors[a].add(b)
        neighbors[b].add(a)
    visited, pending = {0}, [0]
    while pending:
        new = neighbors[pending.pop()]-visited
        visited.update(new)
        pending.extend(new)
    require(len(visited) == count, 'LAYOUT_REQUIRES_DISK', 'The area is disconnected.')
