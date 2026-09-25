"""Separate touching vertex fans without welding or moving their geometry."""
from collections import defaultdict
import numpy as np


def incidences(faces):
    vertices, edges = defaultdict(list), defaultdict(list)
    for face_id, face in enumerate(faces):
        for a, b in zip(face, np.roll(face, -1)):
            vertices[int(a)].append(face_id)
            edges[tuple(sorted((int(a), int(b))))].append(face_id)
    return vertices, edges


def components(face_ids, links):
    pending = set(face_ids); result = []
    while pending:
        group, stack = set(), [min(pending)]
        while stack:
            item = stack.pop()
            if item in pending:
                pending.remove(item); group.add(item); stack.extend(links[item])
        result.append(sorted(group))
    return result


def edge_pairs(vertices, faces, edge, incident):
    triangles = vertices[faces[incident]]; normals = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-30)
    directions = [any(a == edge[0] and b == edge[1] for a, b in zip(faces[i], np.roll(faces[i], -1))) for i in incident]
    pending, result = set(range(len(incident))), []
    while pending:
        a = min(pending); pending.remove(a); choices = [b for b in pending if directions[b] != directions[a]]
        if choices:
            b = max(choices, key=lambda b: (float(normals[a] @ normals[b]), -b)); pending.remove(b)
            result.append((incident[a], incident[b]))
    return result


def split_face(face, edge, midpoint):
    index = next(i for i in range(3) if set((face[i], face[(i+1) % 3])) == set(edge))
    a, b, c = np.roll(face, -index)
    return [int(a), midpoint, int(c)], [midpoint, int(b), int(c)]


def subdivide(vertices, faces, edges):
    extra, replacements, used = [], {}, set()
    for edge, incident in edges.items():
        if len(incident) <= 2 or used.intersection(incident):
            continue
        pairs = edge_pairs(vertices, faces, edge, incident)
        if len(pairs)*2 != len(incident):
            continue
        used.update(incident)
        for pair in pairs:
            midpoint = len(vertices)+len(extra); extra.append(vertices[list(edge)].mean(axis=0))
            for face in pair: replacements[face] = split_face(faces[face], edge, midpoint)
    output = [part for i, face in enumerate(faces) for part in replacements.get(i, [face.tolist()])]
    return np.vstack((vertices, np.asarray(extra).reshape(-1, 3))), np.asarray(output, dtype=int), bool(extra)


def split(vertices, faces):
    for _ in range(16):
        _incidence, edges = incidences(faces)
        vertices, faces, changed = subdivide(vertices, faces, edges)
        if not changed:
            break
    return split_fans(vertices, faces)


def split_fans(vertices, faces):
    incidence, edges = incidences(faces); adjacency = defaultdict(lambda: defaultdict(list))
    for (a, b), incident in edges.items():
        for pair in edge_pairs(vertices, faces, (a, b), incident):
            for vertex in (a, b):
                adjacency[vertex][pair[0]].append(pair[1]); adjacency[vertex][pair[1]].append(pair[0])
    output, result = [], faces.copy()
    for vertex, face_ids in incidence.items():
        for group in components(face_ids, adjacency[vertex]):
            index = len(output); output.append(vertices[vertex])
            for face in group:
                result[face, faces[face] == vertex] = index
    return np.asarray(output), result
