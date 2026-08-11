from heapq import heappop, heappush
from math import dist


_EPS = 1.0e-12


def attachment_feather_weights(vertices, faces, core_indices, amount, scale_indices=()):
    points = tuple(tuple(float(value) for value in point) for point in vertices)
    core = {int(index) for index in core_indices if 0 <= int(index) < len(points)}
    values = [1.0 if index in core else 0.0 for index in range(len(points))]
    scale = _scale_points(points, scale_indices)
    width = max(0.0, min(1.0, float(amount))) * _bounds_diagonal(scale)
    if not core or width <= _EPS:
        return tuple(values)
    distances = _geodesic_distances(points, faces, core, width)
    return tuple(1.0 if index in core else _falloff(distance, width)
                 for index, distance in enumerate(distances))


def _scale_points(points, indices):
    valid = tuple(int(index) for index in indices if 0 <= int(index) < len(points))
    return tuple(points[index] for index in valid) if valid else points


def _bounds_diagonal(points):
    if not points:
        return 0.0
    axes = tuple(zip(*points))
    return sum((max(axis) - min(axis)) ** 2 for axis in axes) ** 0.5


def _geodesic_distances(points, faces, sources, limit):
    graph = _weighted_adjacency(points, faces)
    values = [float("inf")] * len(points)
    queue = []
    for index in sources:
        values[index] = 0.0
        heappush(queue, (0.0, index))
    _visit_graph(graph, values, queue, float(limit))
    return tuple(values)


def _visit_graph(graph, values, queue, limit):
    while queue:
        distance, index = heappop(queue)
        if distance > values[index] or distance > limit:
            continue
        for neighbor, length in graph[index]:
            _relax_neighbor(values, queue, neighbor, distance + length, limit)


def _relax_neighbor(values, queue, index, candidate, limit):
    if candidate >= values[index] or candidate > limit:
        return
    values[index] = candidate
    heappush(queue, (candidate, index))


def _weighted_adjacency(points, faces):
    graph = [dict() for _point in points]
    for face in faces:
        for first, second in _face_edges(face):
            length = dist(points[first], points[second])
            graph[first][second] = min(graph[first].get(second, length), length)
            graph[second][first] = min(graph[second].get(first, length), length)
    return tuple(tuple(row.items()) for row in graph)


def _face_edges(face):
    values = tuple(int(index) for index in face)
    return tuple((values[index], values[(index + 1) % len(values)]) for index in range(len(values)))


def _falloff(distance, width):
    value = max(0.0, min(1.0, 1.0 - float(distance) / max(float(width), _EPS)))
    return value * value * (3.0 - 2.0 * value)
