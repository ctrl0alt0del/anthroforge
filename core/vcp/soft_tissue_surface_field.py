import heapq


def boundary_falloff_weights(vertex_count, edges, faces, vertices=None):
    boundary = boundary_vertex_indices(edges, faces)
    if not boundary:
        return tuple(1.0 for _ in range(vertex_count))
    distances = _distances(vertex_count, edges, boundary, vertices)
    maximum = max(distances) if distances else 0.0
    return tuple(_smooth(value / maximum) if maximum > 0.0 else 0.0 for value in distances)


def boundary_vertex_indices(edges, faces):
    counts = _edge_face_counts(faces)
    return tuple(sorted({v for edge in edges if counts.get(_key(edge), 0) == 1 for v in edge}))


def boundary_edges(edges, faces):
    counts = _edge_face_counts(faces)
    return tuple((face[index], face[(index + 1) % len(face)])
                 for face in faces for index in range(len(face))
                 if counts[_key((face[index], face[(index + 1) % len(face)]))] == 1)


def _edge_face_counts(faces):
    counts = {}
    for face in faces:
        for index in range(len(face)):
            key = _key((face[index], face[(index + 1) % len(face)]))
            counts[key] = counts.get(key, 0) + 1
    return counts


def _distances(count, edges, boundary, vertices):
    graph = _adjacency(count, edges, vertices)
    values = [float("inf")] * int(count)
    queue = []
    for index in boundary:
        values[int(index)] = 0.0
        heapq.heappush(queue, (0.0, int(index)))
    _walk_distances(queue, graph, values)
    return values


def _walk_distances(queue, graph, values):
    while queue:
        distance, index = heapq.heappop(queue)
        if distance > values[index]:
            continue
        for neighbor, weight in graph[index]:
            _relax_distance(queue, values, index, neighbor, weight)


def _relax_distance(queue, values, index, neighbor, weight):
    candidate = values[index] + float(weight)
    if candidate >= values[neighbor]:
        return
    values[neighbor] = candidate
    heapq.heappush(queue, (candidate, neighbor))


def _adjacency(count, edges, vertices):
    graph = [[] for _ in range(int(count))]
    for first, second in edges:
        weight = _edge_length(vertices, int(first), int(second))
        graph[int(first)].append((int(second), weight))
        graph[int(second)].append((int(first), weight))
    return graph


def _edge_length(vertices, first, second):
    if vertices is None:
        return 1.0
    return sum((float(vertices[first][axis]) - float(vertices[second][axis])) ** 2 for axis in range(3)) ** 0.5


def _key(edge):
    return tuple(sorted((int(edge[0]), int(edge[1]))))


def _smooth(value):
    x = max(0.0, min(1.0, float(value)))
    return x * x * (3.0 - 2.0 * x)
