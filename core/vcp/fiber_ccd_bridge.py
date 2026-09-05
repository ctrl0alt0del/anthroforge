import os

import numpy as np

from .fiber_ccd_native import candidate_pairs_native, native_available, pair_collision_free_step_native
from .fiber_collision import _collider_surface


_NATIVE_ENV = "ANTHROFORGE_FIBER_NATIVE_CCD"


def native_ccd_enabled(environment=None):
    values = os.environ if environment is None else environment
    return str(values.get(_NATIVE_ENV, "")).strip().lower() in {"1", "true", "yes"} and native_available()


def _snapshot(oracle):
    cached = getattr(oracle, "_native_ccd_snapshot", None)
    if cached is None:
        cached = _build_snapshot(oracle.colliders())
        oracle._native_ccd_snapshot = cached
    return cached


def _build_snapshot(colliders):
    vertices, triangles, owners, offset = [], [], [], 0
    for index, collider in enumerate(colliders):
        surface = _collider_surface(collider) or {}
        local_vertices = np.asarray([tuple(v) for v in surface.get("verts_world", ())], dtype=np.float64)
        local_triangles = np.asarray(surface.get("triangles", ()), dtype=np.int64).reshape((-1, 3))
        vertices.append(local_vertices); triangles.append(local_triangles + offset)
        owners.extend([index] * len(local_triangles)); offset += len(local_vertices)
    return _joined(vertices, 3, float), _joined(triangles, 3, np.int64), np.asarray(owners), tuple(colliders)


def _joined(values, width, dtype):
    present = [value for value in values if len(value)]
    return np.ascontiguousarray(np.vstack(present), dtype=dtype) if present else np.empty((0, width), dtype=dtype)


def _edge_array(count, cyclic):
    edges = [(index, index + 1) for index in range(max(0, count - 1))]
    if cyclic and count > 2:
        edges.append((count - 1, 0))
    return np.asarray(edges, dtype=np.int64).reshape((-1, 2))


def _combined_interval(solver, start, end, edge, oracle, collider, params, zones):
    first = solver._owner_trim_interval(start, *edge, oracle, collider, params, zones)
    second = solver._owner_trim_interval(end, *edge, oracle, collider, params, zones)
    if first is None or second is None:
        return None
    return min(first[0], second[0]), max(first[1], second[1])


def _trimmed_pair(nodes, edge, interval):
    first, second = nodes[int(edge[0])], nodes[int(edge[1])]
    return [tuple(first.lerp(second, float(interval[0]))), tuple(first.lerp(second, float(interval[1])))]


def _prepared_pairs(solver, start, end, edges, candidates, faces, owners, colliders, oracle, params):
    zones = solver._owner_zone_limits(start, oracle, colliders, params)
    starts, ends, triangles = [], [], []
    for edge_index, face_index in candidates:
        edge, collider = edges[int(edge_index)], colliders[int(owners[int(face_index)])]
        interval = _combined_interval(solver, start, end, edge, oracle, collider, params, zones)
        if interval is None:
            continue
        starts.append(_trimmed_pair(start, edge, interval)); ends.append(_trimmed_pair(end, edge, interval))
        triangles.append(faces[int(face_index)])
    return starts, ends, triangles


def native_collision_free_step(solver, start, end, oracle, params, cyclic=False):
    vertices, faces, owners, colliders = _snapshot(oracle)
    edges = _edge_array(len(start), cyclic)
    start_array, end_array = np.asarray(start, dtype=np.float64), np.asarray(end, dtype=np.float64)
    candidates = candidate_pairs_native(start_array, end_array, edges, vertices, faces, params["margin"])
    pairs = _prepared_pairs(solver, start, end, edges, candidates, vertices[faces], owners, colliders, oracle, params)
    return pair_collision_free_step_native(*pairs, clearance=params["margin"])
