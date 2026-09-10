"""Detached triangle geometry queries used by authoring strategies."""
import numpy as np
from .errors import require


def world_vertices(mesh):
    return mesh.vertices @ mesh.matrix[:3, :3].T + mesh.matrix[:3, 3]


def triangles(mesh):
    return world_vertices(mesh)[mesh.triangles]


def normalized(value):
    size = np.linalg.norm(value, axis=-1, keepdims=True)
    require(bool(np.all(size > 1e-14)), "DEGENERATE_GEOMETRY")
    return np.asarray(value) / size


def face_normals(tris):
    raw = np.cross(tris[:, 1]-tris[:, 0], tris[:, 2]-tris[:, 0])
    lengths = np.linalg.norm(raw, axis=1, keepdims=True)
    return np.divide(raw, lengths, out=np.zeros_like(raw, dtype=float), where=lengths > 1e-14)


def ray_hits(tris, origin, direction, distance):
    e1, e2 = tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    cross = np.cross(direction, e2)
    det = np.einsum("ij,ij->i", e1, cross)
    inverse = np.divide(1., det, out=np.zeros_like(det), where=np.abs(det) > 1e-12)
    delta = origin - tris[:, 0]
    u = np.einsum("ij,ij->i", delta, cross) * inverse
    q = np.cross(delta, e1)
    v = q @ direction * inverse
    t = np.einsum("ij,ij->i", e2, q) * inverse
    valid = (np.abs(det) > 1e-12) & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)
    indices = np.flatnonzero(valid & (t >= 0) & (t <= distance))
    return [(float(t[i]), int(i), origin + t[i] * direction) for i in indices]


def contains(tris, points):
    result = []
    for point in points:
        vectors = tris - point
        a, b, c = vectors[:, 0], vectors[:, 1], vectors[:, 2]
        lengths = np.linalg.norm(vectors, axis=2)
        numerator = np.einsum("ij,ij->i", a, np.cross(b, c))
        denominator = np.prod(lengths, axis=1)
        denominator += np.einsum("ij,ij->i", a, b) * lengths[:, 2]
        denominator += np.einsum("ij,ij->i", b, c) * lengths[:, 0]
        denominator += np.einsum("ij,ij->i", c, a) * lengths[:, 1]
        result.append(abs(np.sum(2 * np.arctan2(numerator, denominator))) > 2 * np.pi)
    return np.asarray(result)


def closed_mesh(mesh):
    edges = {}
    for a, b, c in mesh.triangles:
        for x, y in ((a, b), (b, c), (c, a)):
            key = tuple(sorted((int(x), int(y))))
            edges.setdefault(key, []).append(int(x) < int(y))
    return bool(edges) and all(len(signs) == 2 and signs[0] != signs[1] for signs in edges.values())


def segment_distance(points, first, last):
    edge = last - first
    size = np.einsum("ij,ij->i", edge, edge)
    t = np.divide(np.einsum("ij,ij->i", points - first, edge), size,
                  out=np.zeros_like(size), where=size > 1e-24)
    return np.linalg.norm(points - first - np.clip(t, 0, 1)[:, None] * edge, axis=1)


def surface_distance(tris, point):
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    normal = normalized(np.cross(b - a, c - a))
    signed = np.einsum("ij,ij->i", point - a, normal)
    projected = point - signed[:, None] * normal
    inside = np.ones(len(tris), dtype=bool)
    for first, last in ((a, b), (b, c), (c, a)):
        inside &= np.einsum("ij,ij->i", np.cross(last - first, projected - first), normal) >= -1e-12
    edge = np.minimum.reduce([segment_distance(point, x, y) for x, y in ((a, b), (b, c), (c, a))])
    return float(np.min(np.where(inside, np.abs(signed), edge)))
