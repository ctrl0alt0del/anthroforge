"""Private ctypes binding for the packaged Fiber V2 collision DLL."""

from ctypes import CDLL, POINTER, Structure, byref, c_double, c_int, c_int64, c_void_p
from pathlib import Path

import numpy as np


V2_NATIVE_ABI = 1
V2_NATIVE_CAPABILITIES = 511


class _NativeMeshSweep(Structure):
    _fields_ = [("safe", c_double)]
    _fields_ += [(name, c_int) for name in ("possible", "valid", "tested", "intervals", "reason")]


class _NativeWorldBatch(Structure):
    _fields_ = [(name, c_int) for name in ("candidates", "tested", "rejected", "contained")]
    _fields_ += [("minimum", c_double)]


class _NativeWorldSearch(Structure):
    _fields_ = [(name, c_int) for name in ("path_count", "status", "searches", "expansions",
                                                   "validated", "rejected", "candidates", "tested")]
    _fields_ += [(name, c_double) for name in ("search_ms", "collision_ms")]


_REASONS = ("CLEAR", "AABB_CLEAR", "INVALID_START", "POSSIBLE_COLLISION", "BUDGET_EXHAUSTED")
_LIBRARIES = {}


def native_path():
    return Path(__file__).resolve().parents[3] / "native" / "fiber_ccd" / "af_fiber_ccd.dll"


def clear_native_libraries():
    _LIBRARIES.clear()


def _configure(library):
    _configure_collision_calls(library)
    _configure_snapshot_calls(library)
    _configure_world_calls(library)
    return library


def _configure_collision_calls(library):
    double, integer = POINTER(c_double), POINTER(c_int64)
    library.af_candidate_pairs.argtypes = [double, double, integer, c_int, double, integer,
                                           c_int, c_double, integer]
    library.af_candidate_pairs.restype = c_int
    library.af_segment_triangle_distances.argtypes = [double, double, c_int, double]
    library.af_segment_triangle_distances.restype = c_int
    library.af_mesh_pair_safe_step.argtypes = [double, double, double, c_int, c_double,
                                               c_double, c_int, POINTER(_NativeMeshSweep)]
    library.af_mesh_pair_safe_step.restype = c_int
    library.af_points_inside_closed_mesh.argtypes = [double, c_int, double, integer,
                                                     c_int, POINTER(c_int)]
    library.af_points_inside_closed_mesh.restype = c_int


def _configure_snapshot_calls(library):
    double, integer = POINTER(c_double), POINTER(c_int64)
    library.af_triangle_snapshot_create.argtypes = [double, integer, c_int]
    library.af_triangle_snapshot_create.restype = c_void_p
    library.af_triangle_snapshot_destroy.argtypes = [c_void_p]
    library.af_snapshot_candidate_pairs.argtypes = [c_void_p, double, double, integer,
                                                     c_int, c_double, integer]
    library.af_snapshot_candidate_pairs.restype = c_int
    library.af_snapshot_segment_triangle_distances.argtypes = [c_void_p, double, integer,
                                                                c_int, double]
    library.af_snapshot_segment_triangle_distances.restype = c_int
    library.af_snapshot_points_inside_range.argtypes = [c_void_p, double, c_int, c_int,
                                                         c_int, POINTER(c_int)]
    library.af_snapshot_points_inside_range.restype = c_int


def _configure_world_calls(library):
    double, integer, plain = POINTER(c_double), POINTER(c_int64), POINTER(c_int)
    library.af_world_create.restype = c_void_p
    library.af_world_destroy.argtypes = [c_void_p]
    library.af_world_add_collider.argtypes = [c_void_p, double, integer, c_int, c_int, c_int,
                                               c_int, double, double]
    library.af_world_add_collider.restype = c_int
    library.af_world_commit.argtypes = [c_void_p]; library.af_world_commit.restype = c_int
    library.af_world_update_transform.argtypes = [c_void_p, c_int, double, double]
    library.af_world_update_transform.restype = c_int
    _configure_world_queries(library, double, integer, plain)


def _configure_world_queries(library, double, integer, plain):
    library.af_world_validate_edges.argtypes = [c_void_p, double, integer, plain, plain, c_int,
                                                 c_double, c_double, plain, plain, double,
                                                 POINTER(_NativeWorldBatch)]
    library.af_world_validate_edges.restype = c_int
    library.af_world_validate_instance.argtypes = [c_void_p, c_int, double, integer, plain, plain,
                                                    c_int, c_double, c_double, plain, plain, double,
                                                    POINTER(_NativeWorldBatch)]
    library.af_world_validate_instance.restype = c_int
    _configure_nearest_query(library, double, plain)
    library.af_world_lazy_path.argtypes = [c_void_p, double, c_int, integer, integer, c_int, c_int,
                                            c_double, c_double, c_int, integer, c_int,
                                            POINTER(_NativeWorldSearch)]
    library.af_world_lazy_path.restype = c_int
    _configure_graph_queries(library, double, integer)


def _configure_nearest_query(library, double, plain):
    library.af_world_nearest_points.argtypes = [c_void_p, double, c_int, double, double,
                                                 double, plain, plain]
    library.af_world_nearest_points.restype = c_int


def _configure_graph_queries(library, double, integer):
    library.af_graph_shortest_path.argtypes = [double, c_int, integer, integer, c_int, c_int,
                                                integer, c_int, POINTER(_NativeWorldSearch)]
    library.af_graph_shortest_path.restype = c_int
    library.af_mesh_shortest_path.argtypes = [double, c_int, integer, c_int, c_int, c_int,
                                               integer, c_int, POINTER(_NativeWorldSearch)]
    library.af_mesh_shortest_path.restype = c_int


def load_native(path=None):
    key = str(Path(path or native_path()).resolve())
    if key not in _LIBRARIES:
        _LIBRARIES[key] = _configure(CDLL(key))
    return _LIBRARIES[key]


def native_status(path=None):
    try:
        library = load_native(path)
        version, capabilities = library.af_fiber_ccd_version(), library.af_fiber_ccd_capabilities()
        available = version == V2_NATIVE_ABI and capabilities & V2_NATIVE_CAPABILITIES == V2_NATIVE_CAPABILITIES
        return available, f"af_fiber_ccd-{version}.{capabilities}", "" if available else "incompatible ABI"
    except (OSError, AttributeError) as error:
        return False, "", str(error)


def _double(array):
    return array.ctypes.data_as(POINTER(c_double))


def _integer(array):
    return array.ctypes.data_as(POINTER(c_int64))


class NativeTriangleSnapshot:
    def __init__(self, vertices, triangles, path=None):
        self.library = load_native(path)
        self.handle = self.library.af_triangle_snapshot_create(
            _double(vertices), _integer(triangles), len(triangles))
        if not self.handle:
            raise RuntimeError("native triangle snapshot creation failed")

    def close(self):
        if self.handle:
            self.library.af_triangle_snapshot_destroy(self.handle); self.handle = None

    def __del__(self):
        try:
            self.close()
        except (AttributeError, OSError):
            pass


class NativeCollisionWorld:
    def __init__(self, path=None):
        self.library = load_native(path); self.handle = self.library.af_world_create()
        if not self.handle:
            raise RuntimeError("native collision world creation failed")

    def add(self, vertices, triangles, owner, collider, closed, matrix=None):
        points, faces = _world_mesh(vertices, triangles); transform, inverse = _matrices(matrix)
        args = (self.handle, _double(points), _integer(faces), len(faces), int(owner),
                int(collider), int(bool(closed)), _double(transform), _double(inverse))
        index = self.library.af_world_add_collider(*args)
        if index < 0:
            raise ValueError("invalid native collision-world collider")
        return index

    def commit(self):
        if self.library.af_world_commit(self.handle):
            raise RuntimeError("native collision-world commit failed")

    def update_transform(self, index, matrix):
        transform, inverse = _matrices(matrix)
        code = self.library.af_world_update_transform(self.handle, int(index),
                                                       _double(transform), _double(inverse))
        if code:
            raise ValueError("invalid native collision-world transform")

    def validate(self, points, edges, first, second, span, threshold):
        values, links, owners = _world_validation_inputs(points, edges, first, second)
        return self._validate_call(self.library.af_world_validate_edges, (), values, links,
                                   owners, span, threshold)

    def validate_instance(self, index, points, edges, first, second, span, threshold):
        values, links, owners = _world_validation_inputs(points, edges, first, second)
        return self._validate_call(self.library.af_world_validate_instance, (int(index),), values,
                                   links, owners, span, threshold)

    def _validate_call(self, function, prefix, values, links, owners, span, threshold):
        clear = np.empty(len(links), dtype=np.int32); blockers = np.empty_like(clear)
        minima = np.empty(len(links), dtype=np.float64); result = _NativeWorldBatch()
        args = (self.handle, *prefix, _double(values), _integer(links), _plain(owners[0]),
                _plain(owners[1]), len(links), float(span), float(threshold), _plain(clear),
                _plain(blockers), _double(minima), byref(result))
        if function(*args):
            raise ValueError("invalid native collision-world validation")
        return clear.astype(bool), blockers, minima, result

    def lazy_path(self, points, offsets, neighbors, owners, span, threshold, attempts=512):
        values, starts, links = _graph_inputs(points, offsets, neighbors)
        path = np.empty(len(values), dtype=np.int64); result = _NativeWorldSearch()
        args = (self.handle, _double(values), len(values), _integer(starts), _integer(links),
                int(owners[0]), int(owners[1]), float(span), float(threshold), int(attempts),
                _integer(path), len(path), byref(result))
        if self.library.af_world_lazy_path(*args):
            raise ValueError("invalid native collision-world graph")
        return path[:result.path_count], result

    def nearest(self, points):
        values = np.ascontiguousarray(points, dtype=np.float64)
        closest = np.empty_like(values); normals = np.empty_like(values)
        distances = np.empty(len(values), dtype=np.float64); blockers = np.empty(len(values), dtype=np.int32)
        contained = np.empty(len(values), dtype=np.int32)
        args = (self.handle, _double(values), len(values), _double(closest), _double(normals),
                _double(distances), _plain(blockers), _plain(contained))
        if self.library.af_world_nearest_points(*args):
            raise ValueError("invalid native collision-world nearest query")
        return closest, normals, distances, blockers, contained.astype(bool)

    def close(self):
        if self.handle:
            self.library.af_world_destroy(self.handle); self.handle = None

    def __del__(self):
        try:
            self.close()
        except (AttributeError, OSError):
            pass


def _world_mesh(vertices, triangles):
    points = np.ascontiguousarray(vertices, dtype=np.float64)
    faces = np.ascontiguousarray(triangles, dtype=np.int64)
    if points.ndim != 2 or points.shape[1:] != (3,) or faces.ndim != 2 or faces.shape[1:] != (3,) or not len(faces):
        raise ValueError("collision-world mesh requires vertices and triangles")
    return points, faces


def _matrices(matrix):
    transform = np.eye(4) if matrix is None else np.asarray(matrix, dtype=np.float64)
    if transform.shape != (4, 4) or not np.isfinite(transform).all():
        raise ValueError("collision-world transform must be finite 4x4")
    return np.ascontiguousarray(transform), np.ascontiguousarray(np.linalg.inv(transform))


def _plain(array):
    return array.ctypes.data_as(POINTER(c_int))


def _world_validation_inputs(points, edges, first, second):
    values = np.ascontiguousarray(points, dtype=np.float64); links = np.ascontiguousarray(edges, dtype=np.int64)
    owners = (np.ascontiguousarray(first, dtype=np.int32), np.ascontiguousarray(second, dtype=np.int32))
    if values.ndim != 2 or values.shape[1:] != (3,) or links.ndim != 2 or links.shape[1:] != (2,) or len(owners[0]) != len(links):
        raise ValueError("invalid collision-world edge arrays")
    return values, links, owners


def _graph_inputs(points, offsets, neighbors):
    values = np.ascontiguousarray(points, dtype=np.float64)
    starts = np.ascontiguousarray(offsets, dtype=np.int64); links = np.ascontiguousarray(neighbors, dtype=np.int64)
    if values.ndim != 2 or values.shape[1:] != (3,) or len(starts) != len(values) + 1:
        raise ValueError("invalid native graph arrays")
    return values, starts, links


def native_shortest_path(points, neighbors, start, goal, path=None):
    offsets, links = _neighbor_csr_native(neighbors); values, offsets, links = _graph_inputs(points, offsets, links)
    output = np.empty(len(values), dtype=np.int64); result = _NativeWorldSearch()
    args = (_double(values), len(values), _integer(offsets), _integer(links), int(start), int(goal),
            _integer(output), len(output), byref(result))
    if load_native(path).af_graph_shortest_path(*args):
        raise ValueError("invalid native shortest-path graph")
    return output[:result.path_count], result


def _neighbor_csr_native(neighbors):
    lengths = np.asarray([len(row) for row in neighbors], dtype=np.int64)
    offsets = np.empty(len(neighbors) + 1, dtype=np.int64); offsets[0] = 0
    np.cumsum(lengths, out=offsets[1:])
    links = np.asarray([value for row in neighbors for value in row], dtype=np.int64)
    return offsets, links


def native_mesh_shortest_path(points, triangles, start, goal, path=None):
    values, faces = _world_mesh(points, triangles); output = np.empty(len(values), dtype=np.int64)
    result = _NativeWorldSearch(); args = (_double(values), len(values), _integer(faces), len(faces),
                                           int(start), int(goal), _integer(output), len(output), byref(result))
    if load_native(path).af_mesh_shortest_path(*args):
        raise ValueError("invalid native surface graph")
    return output[:result.path_count], result


def native_snapshot(vertices, triangles, path=None):
    return NativeTriangleSnapshot(vertices, triangles, path)


def native_candidates(start, end, edges, vertices, triangles, padding, path=None, snapshot=None):
    if snapshot is not None:
        return _snapshot_candidates(snapshot, start, end, edges, padding)
    library = load_native(path)
    args = (_double(start), _double(end), _integer(edges), len(edges), _double(vertices),
            _integer(triangles), len(triangles), float(padding))
    count = library.af_candidate_pairs(*args, None)
    result = np.empty((count, 2), dtype=np.int64)
    library.af_candidate_pairs(*args, _integer(result))
    return result


def _snapshot_candidates(snapshot, start, end, edges, padding):
    args = (snapshot.handle, _double(start), _double(end), _integer(edges), len(edges), float(padding))
    count = snapshot.library.af_snapshot_candidate_pairs(*args, None)
    if count < 0:
        raise ValueError("invalid native snapshot candidate arguments")
    result = np.empty((count, 2), dtype=np.int64)
    snapshot.library.af_snapshot_candidate_pairs(*args, _integer(result))
    return result


def native_distances(segments, triangles, path=None):
    output = np.empty(len(segments), dtype=np.float64)
    code = load_native(path).af_segment_triangle_distances(
        _double(segments), _double(triangles), len(segments), _double(output))
    if code:
        raise ValueError("invalid native static-distance arguments")
    return output


def native_snapshot_distances(snapshot, segments, faces):
    output = np.empty(len(segments), dtype=np.float64)
    code = snapshot.library.af_snapshot_segment_triangle_distances(
        snapshot.handle, _double(segments), _integer(faces), len(segments), _double(output))
    if code:
        raise ValueError("invalid native snapshot-distance arguments")
    return output


def native_inside(points, vertices, triangles, path=None):
    output = np.empty(len(points), dtype=np.int32)
    args = (_double(points), len(points), _double(vertices), _integer(triangles),
            len(triangles), output.ctypes.data_as(POINTER(c_int)))
    if load_native(path).af_points_inside_closed_mesh(*args):
        raise ValueError("invalid native containment arguments")
    return output.astype(bool)


def native_snapshot_inside(snapshot, points, face_start, face_count):
    output = np.empty(len(points), dtype=np.int32)
    code = snapshot.library.af_snapshot_points_inside_range(
        snapshot.handle, _double(points), len(points), int(face_start), int(face_count),
        output.ctypes.data_as(POINTER(c_int)))
    if code:
        raise ValueError("invalid native snapshot-containment arguments")
    return output.astype(bool)


def native_safe_step(starts, ends, triangles, clearance, tolerance, budget, path=None):
    output = _NativeMeshSweep()
    args = (_double(starts), _double(ends), _double(triangles), len(starts), float(clearance),
            float(tolerance), int(budget), byref(output))
    if load_native(path).af_mesh_pair_safe_step(*args):
        raise ValueError("invalid native CCD arguments")
    reason = _REASONS[output.reason] if 0 <= output.reason < len(_REASONS) else "ERROR"
    return output.safe, bool(output.possible), bool(output.valid), output.tested, output.intervals, reason
