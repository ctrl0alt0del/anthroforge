import numpy as np
from collections import Counter, deque
from scipy.spatial import cKDTree

from ..draft_skin.bindings import _project_candidates
from ..warm_start.model import TopologyGuideBinding, TopologySkinBinding
from .constants import REGION_GUIDE, REGION_TRANSITION


def build_topology_skin_binding(vertices, skin_vertices, skin_triangles):
    triangles = np.asarray(skin_vertices)[np.asarray(skin_triangles, dtype=np.int32)]
    candidates = _nearest_candidates(vertices, triangles)
    triangle_indices, barycentric, offsets = _bind_points(vertices, triangles, candidates)
    return TopologySkinBinding(triangle_indices, barycentric, offsets, 1)


def build_topology_guide_binding(vertices, quads, regions, guide_indices, guides):
    vertex_guides, rows = _vertex_guide_labels(len(vertices), quads, regions, guide_indices)
    rows = _guide_rows(vertices, quads, regions, guide_indices, vertex_guides, rows)
    parameters = np.full(len(vertices), -1.0, dtype=np.float32)
    for index, guide in enumerate(guides):
        mask = vertex_guides == index
        guide_points = guide.points if hasattr(guide, "points") else guide
        parameters[mask] = _guide_parameters(np.asarray(vertices)[mask], guide_points)
    return TopologyGuideBinding(vertex_guides, rows, parameters, 1)


def _nearest_candidates(vertices, triangles):
    count = min(24, len(triangles))
    _distance, indices = cKDTree(triangles.mean(axis=1)).query(vertices, k=count)
    return np.asarray(indices, dtype=np.int32).reshape(len(vertices), count)


def _bind_points(vertices, triangles, candidates):
    indices, barycentric, offsets = [], [], []
    for point, choices in zip(np.asarray(vertices), candidates):
        bary, projected = _project_candidates(point, triangles[choices])
        selected = int(np.argmin(np.linalg.norm(projected - point, axis=1)))
        indices.append(choices[selected]); barycentric.append(bary[selected])
        offsets.append(_normal_offset(point, triangles[choices[selected]], projected[selected]))
    return np.asarray(indices, np.int32), np.asarray(barycentric, np.float32), np.asarray(offsets, np.float32)


def _normal_offset(point, triangle, projected):
    normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
    normal /= max(float(np.linalg.norm(normal)), 1e-12)
    return float(np.dot(point - projected, normal))


def _vertex_guide_labels(count, quads, regions, guide_indices):
    votes = [[] for _index in range(count)]
    for face, region, guide in zip(quads, regions, guide_indices):
        if region in {REGION_GUIDE, REGION_TRANSITION} and guide >= 0:
            for vertex in face:
                votes[int(vertex)].append((int(guide), int(region)))
    labels = np.asarray([_best_vote(value)[0] for value in votes], np.int32)
    rows = np.asarray([_best_vote(value)[1] for value in votes], np.int32)
    return labels, rows


def _best_vote(votes):
    if not votes:
        return -1, -1
    guides = [value[0] for value in votes]
    guide = max(set(guides), key=guides.count)
    region = max(value[1] for value in votes if value[0] == guide)
    return guide, 0 if region == REGION_GUIDE else -1


def _guide_rows(vertices, quads, regions, face_guides, vertex_guides, rows):
    output = rows.copy()
    for guide in set(vertex_guides.tolist()) - {-1}:
        faces = np.asarray(quads)[(np.asarray(regions) == REGION_GUIDE)
                                  & (np.asarray(face_guides) == guide)]
        if len(faces):
            _assign_rows(vertices, faces, guide, vertex_guides, output)
    return output


def _assign_rows(vertices, faces, guide, vertex_guides, output):
    edges = _patch_edges(faces)
    boundary = [edge for edge, count in Counter(edges).items() if count == 1]
    loops = _edge_loops(boundary)
    if not loops:
        return
    outer = max(loops, key=lambda loop: _perimeter(vertices, loop))
    distances = _graph_distances(edges, outer)
    for vertex, distance in distances.items():
        if vertex_guides[vertex] == guide:
            output[vertex] = distance


def _patch_edges(faces):
    return [tuple(sorted((int(face[i]), int(face[(i + 1) % 4]))))
            for face in faces for i in range(4)]


def _edge_loops(edges):
    adjacency = {}
    for first, second in edges:
        adjacency.setdefault(first, []).append(second); adjacency.setdefault(second, []).append(first)
    pending, loops = set(adjacency), []
    while pending:
        loop = _walk_loop(min(pending), adjacency); pending.difference_update(loop); loops.append(loop)
    return loops


def _walk_loop(start, adjacency):
    loop, previous, current = [], -1, start
    while current not in loop:
        loop.append(current)
        choices = [value for value in adjacency[current] if value != previous]
        previous, current = current, choices[0] if choices else start
    return loop


def _perimeter(vertices, loop):
    points = np.asarray(vertices)[np.asarray(loop, dtype=np.int32)]
    return float(np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1).sum())


def _graph_distances(edges, seeds):
    adjacency = {}
    for first, second in set(edges):
        adjacency.setdefault(first, set()).add(second); adjacency.setdefault(second, set()).add(first)
    distances, queue = {int(value): 0 for value in seeds}, deque(map(int, seeds))
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, ()):
            if neighbor not in distances:
                distances[neighbor] = distances[current] + 1; queue.append(neighbor)
    return distances


def _guide_parameters(points, guide_points):
    if not len(points) or not len(guide_points):
        return np.empty(len(points), dtype=np.float32)
    indices = cKDTree(np.asarray(guide_points)).query(points)[1]
    return (np.asarray(indices, dtype=np.float32) / max(1, len(guide_points))).astype(np.float32)
