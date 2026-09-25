"""Clip a paired muscle output to a half-space selected on its base.

Wholly excluded faces are discarded before triangulation. Remaining faces are
triangulated before clipping, so concave polygons cannot bridge a removed region.
Simple polygons use a dominant-plane projection. A nonplanar native quad whose
projection crosses uses the fixed 0-2 diagonal without moving its vertices;
this defines its triangular surface, not a collision repair. Cuts share
vertex identities only across edges that already share input indices.
"""
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class DomainClipResult:
    base_vertices: np.ndarray
    inflated_vertices: np.ndarray
    faces: np.ndarray
    source_faces: np.ndarray
    face_parts: np.ndarray | None


@dataclass
class _ClipState:
    base: list
    inflated: list
    distances: np.ndarray
    intersections: dict = field(default_factory=dict)
    faces: list = field(default_factory=list)
    sources: list = field(default_factory=list)


def _vertices(values, name):
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 3 or not np.isfinite(array).all():
        raise ValueError(f'{name} must be a finite Nx3 array')
    return array


def _plane_values(plane, tolerance):
    if not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError('tolerance must be finite and nonnegative')
    normal = np.asarray(plane['normal'], dtype=np.float64)
    offset, positive = float(plane['offset']), plane.get('keep_positive', True)
    if normal.shape != (3,) or not np.isfinite(normal).all() or not np.isfinite(offset):
        raise ValueError('plane must have a finite normal and offset')
    length = float(np.linalg.norm(normal))
    if not np.isfinite(length) or length == 0 or not isinstance(positive, (bool, np.bool_)):
        raise ValueError('plane needs a nonzero normal and boolean keep_positive')
    sign = 1. if positive else -1.
    return sign * normal / length, sign * offset / length


def _face_indices(face, count):
    array = np.asarray(face)
    if array.ndim != 1 or (array.size and array.dtype.kind not in 'iu'):
        raise ValueError('face indices must be one-dimensional integers')
    if np.any(array < 0) or np.any(array >= count):
        raise ValueError('face index is outside the vertex array')
    result = [int(v) for i, v in enumerate(array) if not i or v != array[i - 1]]
    if len(result) > 1 and result[0] == result[-1]:
        result.pop()
    if len(set(result)) != len(result):
        raise ValueError('face must not repeat a nonadjacent vertex')
    return result


def _part_labels(face_parts, count):
    if face_parts is None:
        return None
    labels = np.asarray(face_parts)
    if labels.shape != (count,):
        raise ValueError('face_parts must contain one scalar label per input face')
    return labels


def _cross2(a, b):
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


def _projection(points):
    points = points - points[0]
    products = np.cross(points, np.roll(points, -1, axis=0))
    normal = products.sum(axis=0)
    if not np.any(normal):
        normal = products[np.argmax(np.linalg.norm(products, axis=1))]
    if not np.any(normal):
        return None, 0.
    projected = np.delete(points, np.argmax(np.abs(normal)), axis=1)
    scale = float(np.max(np.abs(projected)))
    return projected, np.finfo(np.float64).eps * scale * scale * 32


def _segments_intersect(a, b, c, d, epsilon):
    first = _cross2(b - a, np.array([c - a, d - a]))
    second = _cross2(d - c, np.array([a - c, b - c]))
    if min(first) > epsilon or max(first) < -epsilon:
        return False
    if min(second) > epsilon or max(second) < -epsilon:
        return False
    return bool(np.all(np.maximum(np.minimum(a, b), np.minimum(c, d)) <=
                       np.minimum(np.maximum(a, b), np.maximum(c, d))))


def _check_simple(points, epsilon):
    count = len(points)
    for i in range(count):
        for j in range(i + 2, count):
            if i == 0 and j == count - 1:
                continue
            if _segments_intersect(points[i], points[(i + 1) % count],
                                   points[j], points[(j + 1) % count], epsilon):
                raise ValueError('face must be a simple polygon without crossing edges')


def _contains_points(points, triangle, sign, epsilon):
    edges = np.roll(triangle, -1, axis=0) - triangle
    sides = _cross2(edges, points[:, None, :] - triangle)
    return bool(np.any(np.all(sign * sides >= -epsilon, axis=1)))


def _ear_index(points, remaining, sign, epsilon):
    for position, tip in enumerate(remaining):
        triple = (remaining[position - 1], tip, remaining[(position + 1) % len(remaining)])
        triangle = points[list(triple)]
        if sign * _cross2(triangle[1] - triangle[0], triangle[2] - triangle[1]) <= epsilon:
            continue
        others = [index for index in remaining if index not in triple]
        if not _contains_points(points[others], triangle, sign, epsilon):
            return position, triple
    raise ValueError('face cannot be triangulated as a simple projected polygon')


def _ear_triangles(ids, points, sign, epsilon):
    remaining, result = list(range(len(ids))), []
    while len(remaining) > 3:
        position, triangle = _ear_index(points, remaining, sign, epsilon)
        result.append(tuple(ids[index] for index in triangle))
        del remaining[position]
    result.append(tuple(ids[index] for index in remaining))
    return result


def _projected_triangles(ids, points, epsilon):
    area = float(_cross2(points, np.roll(points, -1, axis=0)).sum())
    edges = np.roll(points, -1, axis=0) - points
    turns = _cross2(edges, np.roll(edges, -1, axis=0))
    if not np.any(np.abs(turns) > epsilon):
        return []
    convex = abs(area) > epsilon and np.all(np.sign(area) * turns >= -epsilon)
    if len(ids) > 4 or not convex:
        _check_simple(points, epsilon)
    if abs(area) <= epsilon:
        return []
    return ([(ids[0], ids[i], ids[i + 1]) for i in range(1, len(ids) - 1)] if convex
            else _ear_triangles(ids, points, np.sign(area), epsilon))


def _nonplanar_quad(points):
    if len(points) != 4:
        return False
    edges = points[1:] - points[0]
    scale = float(np.max(np.abs(edges)))
    if scale == 0:
        return False
    edges = edges / scale
    volume = float(np.dot(np.cross(edges[0], edges[1]), edges[2]))
    return abs(volume) > np.finfo(np.float64).eps * 64


def _triangulate(ids, base):
    if len(ids) < 4:
        return [tuple(ids)] if len(ids) == 3 else []
    points, epsilon = _projection(base[ids])
    try:
        return [] if points is None else _projected_triangles(ids, points, epsilon)
    except ValueError:
        if not _nonplanar_quad(base[ids]):
            raise
        return [(ids[0], ids[1], ids[2]), (ids[0], ids[2], ids[3])]


def _dense_faces(faces, count):
    try:
        array = np.asarray(faces)
    except ValueError:
        return None
    if array.ndim != 2 or array.shape[1] not in (3, 4):
        return None
    if array.dtype.kind not in 'iu':
        raise ValueError('face indices must be one-dimensional integers')
    if np.any(array < 0) or np.any(array >= count):
        raise ValueError('face index is outside the vertex array')
    return array.astype(np.int64, copy=False)


def _fallback_faces(base, indexed_faces):
    triangles, sources = [], []
    for index, face in indexed_faces:
        values = _triangulate(_face_indices(face, len(base)), base)
        triangles.extend(values)
        sources.extend([index] * len(values))
    return np.asarray(triangles, dtype=np.int64).reshape((-1, 3)), np.asarray(sources, dtype=np.int64)


def _convex_quads(points):
    points = points - points[:, :1]
    normal = np.cross(points, np.roll(points, -1, axis=1)).sum(axis=1)
    axis = np.argmax(np.abs(normal), axis=1)
    area = normal[np.arange(len(points)), axis]
    edges = np.roll(points, -1, axis=1) - points
    turns = np.take_along_axis(np.cross(edges, np.roll(edges, -1, axis=1)), axis[:, None, None], axis=2)[:, :, 0]
    projected = np.abs(points) * (np.arange(3)[None, None, :] != axis[:, None, None])
    epsilon = np.finfo(np.float64).eps * np.max(projected, axis=(1, 2)) ** 2 * 32
    return (np.abs(area) > epsilon) & np.all(np.sign(area)[:, None] * turns >= -epsilon[:, None], axis=1)


def _quad_triangles(base, faces):
    convex = _convex_quads(base[faces])
    triangles = faces[convex][:, (0, 1, 2, 0, 2, 3)].reshape((-1, 3))
    sources = np.repeat(np.flatnonzero(convex), 2)
    other, provenance = _fallback_faces(base, ((i, faces[i]) for i in np.flatnonzero(~convex)))
    sources = np.concatenate((sources, provenance))
    order = np.argsort(sources, kind='stable')
    return np.concatenate((triangles, other))[order], sources[order]


def _input_triangles(base, faces):
    dense = _dense_faces(faces, len(base))
    if dense is None:
        return _fallback_faces(base, enumerate(faces))
    if dense.shape[1] == 3:
        return dense, np.arange(len(dense), dtype=np.int64)
    return _quad_triangles(base, dense)


def _domain_triangles(base, faces, distances):
    dense = _dense_faces(faces, len(base))
    if dense is None:
        checked = [_face_indices(face, len(base)) for face in faces]
        return _fallback_faces(base, ((i, face) for i, face in enumerate(checked)
                                      if np.any(distances[face] >= 0)))
    repeated = np.any(np.diff(np.sort(dense, axis=1), axis=1) == 0, axis=1)
    for face in dense[repeated]:
        _face_indices(face, len(base))
    retained = np.flatnonzero(np.any(distances[dense] >= 0, axis=1))
    triangles, sources = _input_triangles(base, dense[retained])
    return triangles, retained[sources]


def _intersection(state, first, last):
    edge = tuple(sorted((first, last)))
    if edge not in state.intersections:
        a, b = edge
        weight = state.distances[a] / (state.distances[a] - state.distances[b])
        state.intersections[edge] = len(state.base)
        state.base.append(state.base[a] + weight * (state.base[b] - state.base[a]))
        state.inflated.append(state.inflated[a] + weight * (state.inflated[b] - state.inflated[a]))
    return state.intersections[edge]


def _clip_triangle(state, triangle):
    polygon = []
    for first, last in zip(triangle, (triangle[1], triangle[2], triangle[0])):
        a, b = state.distances[first], state.distances[last]
        if a >= 0:
            polygon.append(first)
        if (a < 0 < b) or (b < 0 < a):
            polygon.append(_intersection(state, first, last))
    return polygon


def _nondegenerate(points):
    edges = np.array([points[1] - points[0], points[2] - points[0]])
    magnitude = float(np.linalg.norm(np.cross(edges[0], edges[1])))
    scale = float(np.max(np.abs(edges)))
    return magnitude > np.finfo(np.float64).eps * scale * scale * 32


def _emit_face(state, triangles, source):
    for triangle in triangles:
        polygon = _clip_triangle(state, triangle)
        for i in range(1, len(polygon) - 1):
            face = (polygon[0], polygon[i], polygon[i + 1])
            if _nondegenerate([state.base[index] for index in face]):
                state.faces.append(face)
                state.sources.append(source)


def _nondegenerate_many(base, triangles):
    points = base[triangles]
    edges = points[:, 1:] - points[:, :1]
    magnitude = np.linalg.norm(np.cross(edges[:, 0], edges[:, 1]), axis=1)
    scale = np.max(np.abs(edges), axis=(1, 2))
    return magnitude > np.finfo(np.float64).eps * scale * scale * 32


def _emit_crossings(state, triangles, sources, indices):
    order = []
    for index in indices:
        previous = len(state.faces)
        _emit_face(state, [triangles[index]], sources[index])
        order.extend([index] * (len(state.faces) - previous))
    return order


def _merge_emitted(state, triangles, sources, retained, crossed_order):
    faces = np.asarray(state.faces, dtype=np.int64).reshape((-1, 3))
    provenance = np.concatenate((sources[retained], np.asarray(state.sources, dtype=np.int64)))
    order = np.argsort(np.concatenate((retained, crossed_order)), kind='stable')
    state.faces = np.concatenate((triangles[retained], faces))[order]
    state.sources = provenance[order]


def _emit_triangles(state, base, triangles, sources):
    values = state.distances[triangles]
    retained = np.flatnonzero(np.all(values >= 0, axis=1))
    retained = retained[_nondegenerate_many(base, triangles[retained])]
    crossed = np.flatnonzero(np.any(values < 0, axis=1) & np.any(values > 0, axis=1))
    crossed_order = _emit_crossings(state, triangles, sources, crossed)
    _merge_emitted(state, triangles, sources, retained, crossed_order)


def _result(state, labels):
    faces = np.asarray(state.faces, dtype=np.int64).reshape((-1, 3))
    sources = np.asarray(state.sources, dtype=np.int64)
    used = np.unique(faces)
    remap = np.full(len(state.base), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    base = np.asarray(state.base, dtype=np.float64).reshape((-1, 3))[used].copy()
    inflated = np.asarray(state.inflated, dtype=np.float64).reshape((-1, 3))[used].copy()
    parts = None if labels is None else labels[sources].copy()
    return DomainClipResult(base, inflated, remap[faces], sources, parts)


def clip_domain(base_vertices, inflated_vertices, faces, plane, face_parts=None, *, tolerance=1e-10):
    """Return compact triangles; normalize plane coefficients without changing its locus."""
    base, inflated = _vertices(base_vertices, 'base_vertices'), _vertices(inflated_vertices, 'inflated_vertices')
    if base.shape != inflated.shape:
        raise ValueError('base and inflated vertices must have identical shapes')
    normal, offset = _plane_values(plane, tolerance)
    faces = list(faces)
    labels = _part_labels(face_parts, len(faces))
    distances = base @ normal - offset
    distances[np.abs(distances) <= tolerance] = 0.
    triangles, sources = _domain_triangles(base, faces, distances)
    state = _ClipState(list(base), list(inflated), distances)
    _emit_triangles(state, base, triangles, sources)
    return _result(state, labels)
