"""Standalone, fail-closed collision backend for Fiber Solver V2."""

from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum

import numpy as np

from .collision_native import (
    NativeCollisionWorld,
    native_candidates, native_distances, native_inside, native_safe_step, native_snapshot,
    native_snapshot_distances, native_snapshot_inside, native_status,
)
from .contracts import V2ColliderSnapshot


V2_COLLISION_VERSION = "fiber-v2-collision-1"
EDGE_BATCH = 64
PAIR_BATCH = 128


class V2CollisionReason(str, Enum):
    CLEAR = "CLEAR"
    COLLISION = "COLLISION"
    INVALID_START = "INVALID_START"
    CCD_UNCERTAIN = "CCD_UNCERTAIN"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"


@dataclass(frozen=True)
class V2BackendStatus:
    available: bool
    version: str = ""
    message: str = ""


@dataclass(frozen=True)
class V2OwnerContact:
    owner_id: str
    node_indices: tuple = ()
    edge_intervals: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "owner_id", str(self.owner_id or ""))
        object.__setattr__(self, "node_indices", tuple(int(value) for value in self.node_indices))
        object.__setattr__(self, "edge_intervals", tuple(_contact_interval(value) for value in self.edge_intervals))
        if not self.owner_id or any(value < 0 for value in self.node_indices):
            raise ValueError("owner contact requires an owner and nonnegative node indices")


@dataclass(frozen=True)
class V2TriangleSnapshot:
    vertices: np.ndarray
    triangles: np.ndarray
    face_owners: tuple
    face_colliders: tuple
    source_count: int
    collider_ranges: tuple
    native: object = None


@dataclass(frozen=True)
class V2StaticClearance:
    valid: bool
    reason: V2CollisionReason
    node_minimum: float
    edge_minimum: float
    node_residual: float
    edge_residual: float
    candidate_pairs: int
    tested_pairs: int
    violating_nodes: tuple = ()
    violating_edges: tuple = ()
    contained_nodes: tuple = ()
    backend_version: str = ""


@dataclass(frozen=True)
class V2SafeStep:
    safe_step: float
    valid: bool
    initially_valid: bool
    reason: V2CollisionReason
    candidate_pairs: int
    tested_pairs: int
    intervals: int
    max_edge_batch: int
    max_pair_batch: int
    backend_version: str = ""


@dataclass
class V2SweepPairCache:
    key: tuple = ()
    pairs: object = None
    priority: tuple = ()
    hits: int = 0
    misses: int = 0

    def resolve(self, key, builder):
        if key == self.key and self.pairs is not None:
            self.hits += 1; return self.pairs
        self.misses += 1; self.key = key; self.pairs = self.order(builder())
        return self.pairs

    def order(self, pairs):
        if not self.priority or not len(pairs):
            return pairs
        first = [index for index, row in enumerate(pairs) if tuple(row) == self.priority]
        if not first:
            return pairs
        self.hits += 1
        return np.concatenate((pairs[first], np.delete(pairs, first, axis=0)))

    def note(self, pair):
        if pair is not None:
            self.priority = tuple(int(value) for value in pair)


@dataclass(frozen=True)
class V2SegmentBatch:
    clear: tuple
    candidate_pairs: int
    tested_pairs: int
    contained_endpoints: tuple = ()
    backend_version: str = ""
    blockers: tuple = ()
    minimum: float = float("inf")


@dataclass(frozen=True)
class V2ContactBatch:
    active: tuple
    factors: np.ndarray
    closest: np.ndarray
    normals: np.ndarray
    distances: np.ndarray
    blockers: tuple
    candidate_pairs: int
    tested_pairs: int
    minimum: float


@dataclass
class V2NativeCollisionWorld:
    native: object
    owner_tokens: dict
    collider_ids: tuple
    instance_indices: tuple
    backend_version: str

    def validate(self, points, edges, edge_owners, span, threshold):
        first, second = self._owner_rows(edge_owners, len(edges))
        clear, blockers, minima, result = self.native.validate(points, edges, first, second, span, threshold)
        return self._batch_result(clear, blockers, minima, result)

    def validate_instance(self, index, points, edges, edge_owners, span, threshold):
        first, second = self._owner_rows(edge_owners, len(edges))
        values = self.native.validate_instance(self.instance_indices[index], points, edges,
                                               first, second, span, threshold)
        return self._batch_result(*values)

    def _owner_rows(self, edge_owners, count):
        owners = _segment_batch_owners(edge_owners, count)
        first = [self.owner_tokens.get(row[0], 0) for row in owners]
        return first, [self.owner_tokens.get(row[1], 0) for row in owners]

    def _batch_result(self, clear, blockers, minima, result):
        ids = tuple(self.collider_ids[index] if 0 <= index < len(self.collider_ids) else "" for index in blockers)
        minimum = float(np.min(minima)) if len(minima) else float("inf")
        return V2SegmentBatch(tuple(clear), result.candidates, result.tested,
                              backend_version=self.backend_version,
                              blockers=ids, minimum=minimum)

    def lazy_path(self, points, neighbors, start_owner, end_owner, span, threshold):
        offsets, links = _neighbor_csr(neighbors)
        owners = (self.owner_tokens.get(str(start_owner or ""), 0),
                  self.owner_tokens.get(str(end_owner or ""), 0))
        return self.native.lazy_path(points, offsets, links, owners, span, threshold)

    def nearest(self, points):
        closest, normals, distances, blockers, contained = self.native.nearest(points)
        ids = tuple(self.collider_ids[index] if 0 <= index < len(self.collider_ids) else ""
                    for index in blockers)
        return closest, normals, distances, ids, contained

    def contacts(self, points, edges, edge_owners, span, threshold, only=(), skip=()):
        first, second = self._owner_rows(edge_owners, len(edges))
        filters = (self._owner_tokens(only, len(edges)), self._owner_tokens(skip, len(edges)))
        rows = self.native.contacts(points, edges, first, second, span, threshold, *filters)
        active, factors, closest, normals, distances, blockers, result = rows
        ids = tuple(self.collider_ids[index] if 0 <= index < len(self.collider_ids) else ""
                    for index in blockers)
        return V2ContactBatch(tuple(active.astype(bool)), factors, closest, normals, distances,
                              ids, result.candidates, result.tested, result.minimum)

    def _owner_tokens(self, owners, count):
        rows = tuple(owners or ())
        if not rows:
            return np.zeros(count, dtype=np.int32)
        if len(rows) != count:
            raise ValueError("contact owner filters must match edge count")
        return np.asarray([self.owner_tokens.get(str(value or ""), 0) for value in rows], dtype=np.int32)

    def update_transform(self, index, matrix):
        self.native.update_transform(self.instance_indices[index], matrix)


class V2CollisionSnapshotCache:
    def __init__(self, max_entries=8):
        self.max_entries = max(1, int(max_entries)); self._rows = OrderedDict()
        self.hits = 0; self.misses = 0

    def get_or_build(self, colliders, generation):
        key = tuple(generation or ())
        if not key:
            raise ValueError("persistent collision snapshots require a generation key")
        if key in self._rows:
            self.hits += 1; self._rows.move_to_end(key); return self._rows[key]
        self.misses += 1; self._rows[key] = build_triangle_snapshot(colliders)
        while len(self._rows) > self.max_entries:
            self._rows.popitem(last=False)
        return self._rows[key]

    def clear(self):
        self._rows.clear(); self.hits = 0; self.misses = 0

    def stats(self):
        return {"entries": len(self._rows), "hits": self.hits, "misses": self.misses}


_SNAPSHOT_CACHE = V2CollisionSnapshotCache()
_WORLD_CACHE = OrderedDict()


def cached_triangle_snapshot(colliders, generation):
    return _SNAPSHOT_CACHE.get_or_build(tuple(colliders or ()), generation)


def clear_triangle_snapshot_cache():
    _SNAPSHOT_CACHE.clear(); _WORLD_CACHE.clear()


def triangle_snapshot_cache_stats():
    return _SNAPSHOT_CACHE.stats()


def build_native_collision_world(colliders, transforms=None):
    items = tuple(colliders or ()); matrices = tuple(transforms or (None,) * len(items))
    if len(matrices) != len(items):
        raise ValueError("transforms must match collider count")
    tokens = _owner_token_map(items); native = NativeCollisionWorld(); indices = []
    for item, matrix in zip(items, matrices):
        vertices = np.asarray(item.vertices, dtype=np.float64)
        triangles = np.asarray(item.triangles, dtype=np.int64)
        indices.append(native.add(vertices, triangles, tokens.get(item.owner_id, 0),
                                  len(indices), _closed_mesh(triangles), matrix))
    native.commit()
    version = collision_backend_status().version
    return V2NativeCollisionWorld(native, tokens, tuple(item.collider_id for item in items),
                                  tuple(indices), version)


def cached_native_collision_world(colliders, generation=()):
    items = tuple(colliders or ()); key = _native_world_key(items, generation)
    if key in _WORLD_CACHE:
        _WORLD_CACHE.move_to_end(key); return _WORLD_CACHE[key]
    _WORLD_CACHE[key] = build_native_collision_world(items)
    while len(_WORLD_CACHE) > 8:
        _WORLD_CACHE.popitem(last=False)
    return _WORLD_CACHE[key]


def clear_native_collision_world_cache():
    _WORLD_CACHE.clear()


def _native_world_key(colliders, generation):
    if generation:
        return tuple(generation)
    return tuple((item.collider_id, item.owner_id, item.generation,
                  hash(item.vertices), hash(item.triangles)) for item in colliders)


def _owner_token_map(colliders):
    owners = sorted({str(item.owner_id or "") for item in colliders if item.owner_id})
    return {owner: index + 1 for index, owner in enumerate(owners)}


def _neighbor_csr(neighbors):
    lengths = np.asarray([len(row) for row in neighbors], dtype=np.int64)
    offsets = np.empty(len(neighbors) + 1, dtype=np.int64); offsets[0] = 0
    np.cumsum(lengths, out=offsets[1:])
    links = np.asarray([value for row in neighbors for value in row], dtype=np.int64)
    return np.ascontiguousarray(offsets), np.ascontiguousarray(links)


def collision_backend_status(path=None):
    available, version, message = native_status(path)
    return V2BackendStatus(available, version, message)


def build_triangle_snapshot(colliders):
    items = tuple(colliders or ())
    if not all(isinstance(item, V2ColliderSnapshot) for item in items):
        raise ValueError("colliders must contain V2ColliderSnapshot values")
    vertices, triangles, owners, ids, ranges, vertex_offset, face_offset = [], [], [], [], [], 0, 0
    for item in items:
        local_vertices = np.asarray(item.vertices, dtype=np.float64)
        vertices.append(local_vertices)
        local_faces = np.asarray(item.triangles, dtype=np.int64)
        triangles.append(local_faces + vertex_offset)
        owners.extend((item.owner_id,) * len(item.triangles)); ids.extend((item.collider_id,) * len(item.triangles))
        ranges.append((item.collider_id, item.owner_id, vertex_offset, len(item.vertices),
                       face_offset, len(item.triangles), _closed_mesh(local_faces),
                       tuple(local_vertices.min(axis=0)), tuple(local_vertices.max(axis=0))))
        vertex_offset += len(item.vertices); face_offset += len(item.triangles)
    return _triangle_snapshot(vertices, triangles, owners, ids, ranges, len(items))


def _triangle_snapshot(vertices, triangles, owners, ids, ranges, count):
    points = np.vstack(vertices) if vertices else np.empty((0, 3), dtype=np.float64)
    faces = np.vstack(triangles) if triangles else np.empty((0, 3), dtype=np.int64)
    points, faces = np.ascontiguousarray(points), np.ascontiguousarray(faces)
    points.setflags(write=False); faces.setflags(write=False)
    status = collision_backend_status()
    handle = native_snapshot(points, faces) if status.available and len(faces) else None
    return V2TriangleSnapshot(points, faces, tuple(owners), tuple(ids), count, tuple(ranges), handle)


def _closed_mesh(triangles):
    if not len(triangles):
        return False
    edges = np.vstack((triangles[:, (0, 1)], triangles[:, (1, 2)], triangles[:, (2, 0)]))
    edges = np.sort(edges, axis=1)
    _unique, counts = np.unique(edges, axis=0, return_counts=True)
    return bool(len(counts) and np.all(counts == 2))


def validate_static_clearance(points, snapshot, clearance, contacts=(), cyclic=False,
                              slack=0.0, backend_path=None):
    status = collision_backend_status(backend_path)
    if not status.available:
        return _unavailable_static(status)
    nodes = _points(points); edges = _chain_edges(len(nodes), cyclic)
    threshold = _threshold(clearance, slack)
    node_rows = _node_rows(nodes, snapshot, contacts, threshold, backend_path)
    edge_rows = _edge_rows(nodes, edges, snapshot, contacts, threshold, backend_path)
    return _static_result(node_rows, edge_rows, threshold, status.version)


def collision_free_step(start, end, snapshot, clearance, contacts=(), cyclic=False,
                        slack=0.0, backend_path=None, time_tolerance=1.0e-5,
                        interval_budget=262143, pair_cache=None,
                        assume_initial_valid=False, pair_envelope=None):
    status = collision_backend_status(backend_path)
    if not status.available:
        return _unavailable_sweep(status)
    source, target = _point_pair(start, end); edges = _chain_edges(len(source), cyclic)
    initial = None if assume_initial_valid else validate_static_clearance(
        source, snapshot, clearance, contacts, cyclic, slack, backend_path)
    if initial is not None and not initial.valid:
        return _invalid_start(initial, status.version)
    return _sweep(source, target, edges, snapshot, contacts, _threshold(clearance, slack),
                  time_tolerance, interval_budget, backend_path, status.version,
                  pair_cache, pair_envelope)


def segment_triangle_distances(segments, triangles, backend_path=None):
    status = collision_backend_status(backend_path)
    if not status.available:
        raise RuntimeError(V2CollisionReason.BACKEND_UNAVAILABLE.value)
    lines = _array(segments, (-1, 2, 3), "segments")
    faces = _array(triangles, (-1, 3, 3), "triangles")
    if len(lines) != len(faces):
        raise ValueError("segments and triangles must contain equal pair counts")
    return native_distances(lines, faces, backend_path)


def point_triangle_distances(points, triangles, backend_path=None):
    values = _array(points, (-1, 3), "points")
    segments = np.repeat(values[:, None, :], 2, axis=1)
    return segment_triangle_distances(segments, triangles, backend_path)


def validate_segment_clearance_batch(points, edges, snapshot, clearance,
                                     edge_owners=(), contact_span=0.0,
                                     slack=0.0, backend_path=None,
                                     containment_cache=None):
    status = collision_backend_status(backend_path)
    values, links = _segment_batch_inputs(points, edges)
    owners = _segment_batch_owners(edge_owners, len(links))
    if not status.available:
        return V2SegmentBatch((False,) * len(links), 0, 0, backend_version=status.version)
    threshold = _threshold(clearance, slack)
    return _segment_batch(values, links, snapshot, owners, float(contact_span),
                          threshold, backend_path, status.version, containment_cache)


def _segment_batch_inputs(points, edges):
    values = _points(points)
    links = np.ascontiguousarray(edges, dtype=np.int64)
    if links.ndim != 2 or links.shape[1:] != (2,) or np.any(links < 0) or np.any(links >= len(values)):
        raise ValueError("edges must have valid shape (M, 2)")
    return values, links


def _segment_batch_owners(owners, count):
    rows = tuple((str(a or ""), str(b or "")) for a, b in tuple(owners or ()))
    if not rows:
        return (("", ""),) * count
    if len(rows) != count:
        raise ValueError("edge_owners must match edge count")
    return rows


def _segment_batch(points, edges, snapshot, owners, span, threshold, path, version, cache):
    pairs = _candidate_pairs(points, points, edges, snapshot, threshold, path)
    segments, faces, keys = _segment_batch_rows(points, edges, snapshot, owners, span, pairs)
    distances = _batch_face_distances(segments, faces, snapshot, path)
    clear = np.ones(len(edges), dtype=bool)
    for distance, edge in zip(distances, keys):
        clear[edge] &= distance >= threshold
    inside = _batch_contained(points, edges, snapshot, owners, path, cache)
    clear[[edge for edge, _node, _owner in inside]] = False
    return V2SegmentBatch(tuple(bool(value) for value in clear), len(pairs), len(keys),
                          tuple(inside), version)


def _segment_batch_rows(points, edges, snapshot, owners, span, pairs):
    if not len(pairs):
        return _empty_segment_rows()
    special = _special_pair_mask(pairs, snapshot, owners, span)
    plain = _plain_segment_rows(points, edges, snapshot, pairs[~special])
    trimmed = _trimmed_segment_rows(points, edges, snapshot, owners, span, pairs[special])
    return tuple(np.concatenate((first, second), axis=0)
                 for first, second in zip(plain, trimmed))


def _special_pair_mask(pairs, snapshot, owners, span):
    if span <= 0.0:
        return np.zeros(len(pairs), dtype=bool)
    rows = np.asarray(owners, dtype=object); edge_indices = pairs[:, 0]
    face_owners = np.asarray(snapshot.face_owners, dtype=object)[pairs[:, 1]]
    return (rows[edge_indices, 0] == face_owners) | (rows[edge_indices, 1] == face_owners)


def _plain_segment_rows(points, edges, snapshot, pairs):
    if not len(pairs):
        return _empty_segment_rows()
    edge_indices, face_indices = pairs[:, 0], pairs[:, 1]
    segments = points[edges[edge_indices]]
    return np.ascontiguousarray(segments), face_indices.copy(), edge_indices.copy()


def _trimmed_segment_rows(points, edges, snapshot, owners, span, pairs):
    segments, faces, keys = [], [], []
    for edge, face in pairs:
        owner = snapshot.face_owners[int(face)]
        for low, high in _batch_intervals(points[edges[edge]], owner, owners[int(edge)], span):
            segments.append(_subsegment(points[edges[edge]], low, high))
            faces.append(int(face))
            keys.append(int(edge))
    return (np.asarray(segments, dtype=np.float64).reshape((-1, 2, 3)),
            np.asarray(faces, dtype=np.int64), np.asarray(keys, dtype=np.int64))


def _empty_segment_rows():
    return (np.empty((0, 2, 3), dtype=np.float64),
            np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64))


def _batch_face_distances(segments, faces, snapshot, path):
    if not len(segments):
        return ()
    lines = np.ascontiguousarray(segments, dtype=np.float64); indices = np.ascontiguousarray(faces)
    if path is None and snapshot.native is not None:
        return native_snapshot_distances(snapshot.native, lines, indices)
    triangles = snapshot.vertices[snapshot.triangles[indices]]
    return _batch_distances(lines, triangles, path)


def _batch_intervals(edge, collider_owner, owners, span):
    length = float(np.linalg.norm(edge[1] - edge[0])); intervals = [(0.0, 1.0)]
    fraction = min(1.0, max(0.0, span / max(length, 1.0e-12)))
    if owners[0] == collider_owner:
        intervals = _subtract(intervals, 0.0, fraction)
    if owners[1] == collider_owner:
        intervals = _subtract(intervals, 1.0 - fraction, 1.0)
    return tuple(intervals)


def _batch_distances(segments, triangles, path):
    if not len(segments):
        return ()
    lines = np.ascontiguousarray(segments, dtype=np.float64)
    faces = np.ascontiguousarray(triangles, dtype=np.float64)
    return np.concatenate([native_distances(lines[i:i + PAIR_BATCH], faces[i:i + PAIR_BATCH], path)
                           for i in range(0, len(lines), PAIR_BATCH)])


def _batch_contained(points, edges, snapshot, owners, path, cache):
    memberships = _edge_memberships(points, edges, snapshot, path, cache); output = []
    for edge_index, (first, second) in enumerate(edges):
        for node, endpoint_owner in ((int(first), owners[edge_index][0]),
                                     (int(second), owners[edge_index][1])):
            output.extend((edge_index, node, owner) for owner in memberships.get(node, ())
                          if owner != endpoint_owner)
    return tuple(dict.fromkeys(output))


def _edge_memberships(points, edges, snapshot, path, cache):
    indices = np.unique(np.asarray(edges, dtype=np.int64).reshape(-1))
    keys = tuple(_point_key(points[index]) for index in indices)
    missing = tuple(index for index, key in enumerate(keys) if cache is None or key not in cache)
    _cache_memberships(points, indices, keys, missing, snapshot, path, cache)
    return _membership_rows(points, indices, keys, snapshot, path, cache)


def _cache_memberships(points, indices, keys, missing, snapshot, path, cache):
    if cache is None or not missing:
        return
    rows = _inside_memberships(points[indices[list(missing)]], snapshot, path)
    for local, missing_index in enumerate(missing):
        cache[keys[missing_index]] = tuple(sorted(rows.get(local, ())))


def _membership_rows(points, indices, keys, snapshot, path, cache):
    if cache is None:
        local = _inside_memberships(points[indices], snapshot, path)
        return {int(indices[index]): owners for index, owners in local.items()}
    return {int(index): cache[key] for index, key in zip(indices, keys) if cache[key]}


def _point_key(point):
    return np.asarray(point, dtype=np.float64).tobytes()


def _inside_memberships(points, snapshot, path):
    output = {}
    for row in snapshot.collider_ranges:
        if not row[6]:
            continue
        indices = _inside_bounds_indices(points, row)
        for index in _inside_range(points, indices, snapshot, row, path):
            output.setdefault(int(index), set()).add(str(row[1]))
    return output


def _inside_bounds_indices(points, row):
    low, high = np.asarray(row[7]), np.asarray(row[8])
    return [int(index) for index in np.flatnonzero(
        np.all(points >= low, axis=1) & np.all(points <= high, axis=1))]


def _contact_interval(value):
    edge, start, end = tuple(value)
    edge, start, end = int(edge), float(start), float(end)
    if edge < 0 or not 0.0 <= start <= end <= 1.0:
        raise ValueError("edge contact intervals require edge >= 0 and 0 <= start <= end <= 1")
    return edge, start, end


def _array(value, shape, name):
    result = np.ascontiguousarray(value, dtype=np.float64)
    sizes_match = result.ndim == len(shape) and all(
        size == -1 or result.shape[index] == size for index, size in enumerate(shape))
    if not sizes_match or not np.isfinite(result).all():
        raise ValueError(f"{name} must have finite shape {shape}")
    return result


def _points(value):
    result = np.ascontiguousarray(value, dtype=np.float64)
    if result.ndim != 2 or result.shape[1:] != (3,) or len(result) < 2 or not np.isfinite(result).all():
        raise ValueError("Fiber points must have finite shape (N, 3), N >= 2")
    return result


def _point_pair(start, end):
    source, target = _points(start), _points(end)
    if source.shape != target.shape:
        raise ValueError("start and end Fiber points must have matching shapes")
    return source, target


def _chain_edges(count, cyclic):
    start = np.arange(count if cyclic else count - 1, dtype=np.int64)
    return np.ascontiguousarray(np.column_stack((start, (start + 1) % count)))


def _threshold(clearance, slack):
    clearance, slack = float(clearance), float(slack)
    if not np.isfinite(clearance) or not np.isfinite(slack) or clearance < 0.0 or slack < 0.0:
        raise ValueError("clearance and slack must be finite and nonnegative")
    return max(0.0, clearance - slack)


def _candidate_pairs(start, end, edges, snapshot, padding, path):
    batches = []
    for first in range(0, len(edges), EDGE_BATCH):
        batch = edges[first:first + EDGE_BATCH]
        handle = snapshot.native if path is None else None
        pairs = native_candidates(start, end, batch, snapshot.vertices, snapshot.triangles,
                                  padding, path, handle)
        if len(pairs):
            pairs[:, 0] += first; batches.append(pairs)
    return np.vstack(batches) if batches else np.empty((0, 2), dtype=np.int64)


def _node_rows(points, snapshot, contacts, threshold, path):
    edges = np.ascontiguousarray(np.column_stack((np.arange(len(points)), np.arange(len(points)))), dtype=np.int64)
    pairs = _candidate_pairs(points, points, edges, snapshot, threshold, path)
    allowed = [(int(node), int(face)) for node, face in pairs
               if not _node_exempt(int(node), snapshot.face_owners[int(face)], contacts)]
    segments = [(points[node], points[node]) for node, _face in allowed]
    faces = [face for _node, face in allowed]
    distances, keys, candidates = _distance_face_rows(segments, faces, allowed, len(pairs), snapshot, path)
    contained = _contained_nodes(points, snapshot, contacts, path)
    return distances, keys, candidates, contained


def _edge_rows(points, edges, snapshot, contacts, threshold, path):
    pairs = _candidate_pairs(points, points, edges, snapshot, threshold, path); segments, faces, keys = [], [], []
    for edge, face in pairs:
        owner = snapshot.face_owners[int(face)]
        for start, end in _tested_intervals(int(edge), owner, contacts):
            segments.append(_subsegment(points[edges[edge]], start, end))
            faces.append(int(face))
            keys.append((int(edge), int(face)))
    return _distance_face_rows(segments, faces, keys, len(pairs), snapshot, path)


def _distance_face_rows(segments, faces, keys, candidates, snapshot, path):
    if not segments:
        return (), (), int(candidates)
    lines = np.ascontiguousarray(segments, dtype=np.float64)
    distances = _batch_face_distances(lines, np.asarray(faces, dtype=np.int64), snapshot, path)
    return tuple(float(value) for value in distances), tuple(keys), int(candidates)


def _distance_rows(segments, triangles, keys, candidates, path):
    if not segments:
        return (), (), int(candidates)
    lines = np.ascontiguousarray(segments, dtype=np.float64)
    faces = np.ascontiguousarray(triangles, dtype=np.float64)
    distances = np.concatenate([native_distances(lines[i:i + PAIR_BATCH], faces[i:i + PAIR_BATCH], path)
                                for i in range(0, len(lines), PAIR_BATCH)])
    return tuple(float(value) for value in distances), tuple(keys), int(candidates)


def _node_exempt(node, owner, contacts):
    return any(item.owner_id == owner and node in item.node_indices for item in contacts)


def _contained_nodes(points, snapshot, contacts, path):
    contained = set()
    for row in snapshot.collider_ranges:
        _collider, owner, _vs, _vc, _fs, _fc, closed, low, high = row
        inside_bounds = np.all(points >= low, axis=1) & np.all(points <= high, axis=1)
        indices = [index for index in np.flatnonzero(inside_bounds)
                   if not _node_exempt(int(index), owner, contacts)]
        if closed and indices:
            contained.update(_inside_range(points, indices, snapshot, row, path))
    return tuple(sorted(contained))


def _inside_range(points, indices, snapshot, row, path):
    _collider, _owner, vertex_start, vertex_count, face_start, face_count, _closed, _low, _high = row
    vertices = snapshot.vertices[vertex_start:vertex_start + vertex_count]
    triangles = snapshot.triangles[face_start:face_start + face_count] - vertex_start
    output = []
    for first in range(0, len(indices), PAIR_BATCH):
        batch = np.asarray(indices[first:first + PAIR_BATCH], dtype=np.int64)
        values = np.ascontiguousarray(points[batch])
        inside = (native_snapshot_inside(snapshot.native, values, face_start, face_count)
                  if path is None and snapshot.native is not None else
                  native_inside(values, vertices, np.ascontiguousarray(triangles), path))
        output.extend(int(index) for index, value in zip(batch, inside) if value)
    return output


def _tested_intervals(edge, owner, contacts):
    intervals = [(0.0, 1.0)]
    excluded = [row[1:] for item in contacts if item.owner_id == owner
                for row in item.edge_intervals if row[0] == edge]
    for start, end in sorted(excluded):
        intervals = _subtract(intervals, start, end)
    return tuple(intervals)


def _subtract(intervals, start, end):
    output = []
    for low, high in intervals:
        if end <= low or start >= high:
            output.append((low, high)); continue
        if start > low:
            output.append((low, min(start, high)))
        if end < high:
            output.append((max(end, low), high))
    return output


def _subsegment(edge_points, start, end):
    delta = edge_points[1] - edge_points[0]
    return np.asarray((edge_points[0] + start * delta, edge_points[0] + end * delta))


def _static_result(nodes, edges, threshold, version):
    node_values, node_keys, node_candidates, contained = nodes
    edge_values, edge_keys, edge_candidates = edges
    node_min = min(node_values, default=float("inf")); edge_min = min(edge_values, default=float("inf"))
    node_bad = tuple(sorted({key[0] for value, key in zip(node_values, node_keys) if value < threshold}))
    edge_bad = tuple(sorted({key[0] for value, key in zip(edge_values, edge_keys) if value < threshold}))
    valid = not node_bad and not edge_bad and not contained
    reason = V2CollisionReason.CLEAR if valid else V2CollisionReason.COLLISION
    return V2StaticClearance(valid, reason, node_min, edge_min, max(0.0, threshold - node_min),
                             max(0.0, threshold - edge_min), node_candidates + edge_candidates,
                             len(node_values) + len(edge_values), node_bad, edge_bad, contained, version)


def _sweep(source, target, edges, snapshot, contacts, clearance, tolerance, budget, path, version,
           pair_cache=None, pair_envelope=None):
    envelope = pair_envelope or (source, target)
    pairs = _cached_candidate_pairs(envelope, edges, snapshot, clearance, path, pair_cache)
    starts, ends, faces, keys = _sweep_rows(source, target, edges, snapshot, contacts, pairs)
    state = [1.0, False, True, 0, 0, "CLEAR"]
    for first in range(0, len(starts), PAIR_BATCH):
        limiting = _advance_sweep(state, starts[first:first + PAIR_BATCH], ends[first:first + PAIR_BATCH],
                                  faces[first:first + PAIR_BATCH], clearance, tolerance, budget, path)
        if pair_cache is not None and limiting >= 0:
            pair_cache.note(keys[first + limiting])
        if not state[2] or state[5] == "BUDGET_EXHAUSTED":
            break
    return _sweep_result(state, len(pairs), min(EDGE_BATCH, len(edges)), min(PAIR_BATCH, len(starts)), version)


def _cached_candidate_pairs(envelope, edges, snapshot, padding, path, cache):
    start, end = envelope; key = _pair_cache_key(start, end, edges, snapshot, padding)
    build = lambda: _candidate_pairs(start, end, edges, snapshot, padding, path)
    return build() if cache is None else cache.resolve(key, build)


def _pair_cache_key(start, end, edges, snapshot, padding):
    return (id(snapshot), float(padding), np.asarray(start).tobytes(),
            np.asarray(end).tobytes(), np.asarray(edges).tobytes())


def _sweep_rows(source, target, edges, snapshot, contacts, pairs):
    starts, ends, faces, keys = [], [], [], []
    for edge, face in pairs:
        owner, points = snapshot.face_owners[int(face)], edges[int(edge)]
        for low, high in _tested_intervals(int(edge), owner, contacts):
            starts.append(_subsegment(source[points], low, high))
            ends.append(_subsegment(target[points], low, high))
            faces.append(snapshot.vertices[snapshot.triangles[face]])
            keys.append((int(edge), int(face)))
    shapes = ((-1, 2, 3), (-1, 2, 3), (-1, 3, 3))
    arrays = tuple(np.ascontiguousarray(value, dtype=np.float64).reshape(shape)
                   for value, shape in zip((starts, ends, faces), shapes))
    return (*arrays, tuple(keys))


def _advance_sweep(state, starts, ends, faces, clearance, tolerance, budget, path):
    if not len(starts):
        return -1
    scaled = starts + state[0] * (ends - starts)
    safe, possible, valid, tested, intervals, reason, limiting = native_safe_step(
        starts, scaled, faces, clearance, tolerance, budget, path)
    state[0] *= safe; state[1] |= possible; state[2] &= valid
    state[3] += tested; state[4] += intervals
    if reason == "BUDGET_EXHAUSTED" or not valid:
        state[5] = reason
    return int(limiting)


def _sweep_result(state, candidates, edge_batch, pair_batch, version):
    safe, possible, valid, tested, intervals, native_reason = state
    uncertain = native_reason == "BUDGET_EXHAUSTED"
    reason = V2CollisionReason.CCD_UNCERTAIN if uncertain else V2CollisionReason.INVALID_START if not valid else V2CollisionReason.COLLISION if possible else V2CollisionReason.CLEAR
    accepted = valid and not uncertain
    return V2SafeStep(float(safe), accepted, valid, reason, int(candidates), int(tested),
                      int(intervals), int(edge_batch), int(pair_batch), version)


def _unavailable_static(status):
    return V2StaticClearance(False, V2CollisionReason.BACKEND_UNAVAILABLE, float("inf"),
                             float("inf"), 0.0, 0.0, 0, 0, backend_version=status.version)


def _unavailable_sweep(status):
    return V2SafeStep(0.0, False, False, V2CollisionReason.BACKEND_UNAVAILABLE,
                      0, 0, 0, 0, 0, status.version)


def _invalid_start(initial, version):
    return V2SafeStep(0.0, False, False, V2CollisionReason.INVALID_START,
                      initial.candidate_pairs, initial.tested_pairs, 0, 0, 0, version)
