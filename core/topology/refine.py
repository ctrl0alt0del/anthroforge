import numpy as np


def refine_quads(vertices, faces, selected):
    values = np.asarray(faces, dtype=np.int32)
    split = _closed_split_edges(values, np.asarray(selected, dtype=bool))
    points, midpoint = _midpoints(np.asarray(vertices, dtype=np.float64), split)
    output, parents = [], []
    for index, face in enumerate(values):
        polygons, points = _refine_face(face, split, midpoint, points)
        output.extend(polygons); parents.extend([index] * len(polygons))
    return np.asarray(points), np.asarray(output, dtype=np.int32), np.asarray(parents, dtype=np.int32)


def _closed_split_edges(faces, selected):
    split = {edge for index, face in enumerate(faces) if selected[index] for edge in _face_edges(face)}
    changed = True
    while changed:
        changed = _close_once(faces, split)
    return split


def _close_once(faces, split):
    changed = False
    for face in faces:
        edges, flags = _face_edges(face), [edge in split for edge in _face_edges(face)]
        if sum(flags) == 1:
            split.add(edges[(flags.index(True) + 2) % 4]); changed = True
        elif sum(flags) == 3:
            split.add(edges[flags.index(False)]); changed = True
    return changed


def _face_edges(face):
    return tuple(tuple(sorted((int(face[i]), int(face[(i + 1) % 4])))) for i in range(4))


def _midpoints(vertices, split):
    points, lookup = list(vertices), {}
    for edge in sorted(split):
        lookup[edge] = len(points); points.append(0.5 * (vertices[edge[0]] + vertices[edge[1]]))
    return points, lookup


def _refine_face(face, split, midpoint, points):
    edges = _face_edges(face); flags = tuple(edge in split for edge in edges)
    if not any(flags):
        return [tuple(map(int, face))], points
    mids = [midpoint.get(edge, -1) for edge in edges]
    if sum(flags) == 2 and flags[0] and flags[2]:
        return _opposite(face, mids, 0), points
    if sum(flags) == 2 and flags[1] and flags[3]:
        return _opposite(face, mids, 1), points
    center = len(points); points.append(np.mean(np.asarray(points)[face], axis=0))
    return (_four(face, mids, center) if sum(flags) == 4 else _adjacent(face, mids, flags, center)), points


def _opposite(face, mids, offset):
    rotated = np.roll(face, -offset); middle = np.roll(mids, -offset)
    return [(int(rotated[0]), middle[0], middle[2], int(rotated[3])),
            (middle[0], int(rotated[1]), int(rotated[2]), middle[2])]


def _four(face, mids, center):
    return [(int(face[i]), mids[i], center, mids[(i - 1) % 4]) for i in range(4)]


def _adjacent(face, mids, flags, center):
    start = next(i for i in range(4) if flags[i] and flags[(i + 1) % 4])
    values, middle = np.roll(face, -start), np.roll(mids, -start)
    return [(int(values[0]), middle[0], center, int(values[3])),
            (middle[0], int(values[1]), middle[1], center),
            (center, middle[1], int(values[2]), int(values[3]))]
