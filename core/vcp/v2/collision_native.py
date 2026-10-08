"""Private ctypes binding for the packaged Fiber V2 collision DLL."""

from ctypes import CDLL, POINTER, Structure, byref, c_double, c_int, c_int64, c_uint64, c_void_p
from os import environ
from pathlib import Path

import numpy as np


V2_NATIVE_ABI = 3
ROADMAP_PREPARATION_CAPABILITY = 134217728
PIN_EXIT_PREPARATION_CAPABILITY = 268435456
V2_NATIVE_CAPABILITIES = 3276799 | ROADMAP_PREPARATION_CAPABILITY | PIN_EXIT_PREPARATION_CAPABILITY
V2_NATIVE_BATCH_CAPABILITY = 1024
V3_NATIVE_SESSION_CAPABILITY = 32768
V3_NATIVE_MULTI_SESSION_CAPABILITY = 65536
V3_NATIVE_CONTROLLER_CAPABILITIES = 5111808
V3_NATIVE_ASYNC_CAPABILITY = 16777216
ATTACHMENT_WAVE_CAPABILITY = 33554432
MUSCLE_NUMERIC_CAPABILITY = 67108864


class _NativeMeshSweep(Structure):
    _fields_ = [("safe", c_double)]
    _fields_ += [(name, c_int) for name in ("possible", "valid", "tested", "intervals",
                                                   "reason", "limiting")]


class _NativeWorldBatch(Structure):
    _fields_ = [(name, c_int) for name in ("candidates", "tested", "rejected", "contained")]
    _fields_ += [("minimum", c_double)]


class _NativeWorldSearch(Structure):
    _fields_ = [(name, c_int) for name in ("path_count", "status", "searches", "expansions",
                                                   "validated", "rejected", "candidates", "tested")]
    _fields_ += [(name, c_double) for name in ("search_ms", "collision_ms")]


class _NativeWorldContacts(Structure):
    _fields_ = [(name, c_int) for name in ("candidates", "tested", "active", "contained")]
    _fields_ += [("minimum", c_double)]


class _NativeBlockResult(Structure):
    _fields_ = [(name, c_double) for name in ("condition", "assembly_ms", "factor_ms", "solve_ms")]
    _fields_ += [("count", c_int), ("valid", c_int)]


class _NativeContactPair(Structure):
    _fields_ = [(name, c_int) for name in ("edge", "collider", "instance", "face", "contained")]
    _fields_ += [("factor", c_double), ("distance", c_double)]
    _fields_ += [(name, c_double * 3) for name in ("closest", "normal")]


class _NativeV3SessionStats(Structure):
    _fields_ = [(name, c_uint64) for name in ("measures", "contact_queries", "validations",
                                               "structural_solves", "sweeps")]
    _fields_ += [(name, c_int) for name in ("edge_capacity", "contact_capacity", "sweep_capacity")]


class _NativeV3CcdStats(Structure):
    _fields_ = [(name, c_uint64) for name in ("serial_sweeps", "indexed_sweeps", "indexed_clear",
        "indexed_fallbacks", "serial_clear", "candidate_pairs", "indexed_pairs", "serial_tests",
        "serial_intervals")]


class _NativeV3BatchSweepJob(Structure):
    _fields_ = [("session", c_void_p), ("source", POINTER(c_double)),
                ("target", POINTER(c_double)), ("clearance", c_double),
                ("tolerance", c_double)]
    _fields_ += [(name, c_int) for name in ("budget", "status", "candidates", "pairs", "edge", "face")]
    _fields_ += [("elapsed_ms", c_double), ("result", _NativeMeshSweep)]


class _NativeV3BatchStats(Structure):
    _fields_ = [(name, c_int) for name in ("submitted", "completed", "workers")]
    _fields_ += [("elapsed_ms", c_double)]


_REASONS = ("CLEAR", "AABB_CLEAR", "INVALID_START", "POSSIBLE_COLLISION", "BUDGET_EXHAUSTED")
_LIBRARIES = {}
_DEFAULT_NATIVE_PATH = Path(__file__).resolve().parents[3] / "native" / "fiber_ccd" / "af_fiber_ccd_v3_32.dll"


def native_path():
    return _DEFAULT_NATIVE_PATH


def clear_native_libraries():
    _LIBRARIES.clear()


def _configure(library):
    _configure_thread_calls(library)
    _configure_collision_calls(library)
    _configure_snapshot_calls(library)
    _configure_world_calls(library)
    _configure_v3_calls(library)
    return library


def _configure_thread_calls(library):
    library.af_fiber_worker_threads.restype = c_int
    library.af_fiber_indexed_ccd_threshold.restype = c_int
    library.af_fiber_indexed_ccd_parallel.argtypes = [c_int]
    library.af_fiber_indexed_ccd_parallel.restype = c_int
    library.af_fiber_set_worker_threads.argtypes = [c_int]
    library.af_fiber_set_worker_threads.restype = c_int
    if library.af_fiber_set_worker_threads(_requested_native_threads()):
        raise ValueError("invalid native Fiber worker count")


def _requested_native_threads():
    raw = environ.get("AF_FIBER_NATIVE_THREADS", "4").strip()
    try: value = int(raw)
    except ValueError as error: raise ValueError("AF_FIBER_NATIVE_THREADS must be an integer") from error
    if value < 1 or value > 64: raise ValueError("AF_FIBER_NATIVE_THREADS must be in [1, 64]")
    return value


def _configure_v3_calls(library):
    double, integer, plain = POINTER(c_double), POINTER(c_int64), POINTER(c_int)
    _configure_block_calls(library, double)
    _configure_contact_pair_call(library, double, integer, plain)
    _configure_contact_solve_call(library, double, integer)
    _configure_response_call(library, double, integer)
    _configure_v3_session_calls(library, double, integer, plain)


def _configure_v3_session_calls(library, double, integer, plain):
    _configure_v3_session_lifecycle(library, plain)
    _configure_v3_session_collision(library, double, plain)
    _configure_v3_session_solver(library, double, integer)
    _configure_v3_batch_calls(library)


def _configure_v3_batch_calls(library):
    library.af_v3_batch_safe_steps.argtypes = [POINTER(_NativeV3BatchSweepJob), c_int,
                                                POINTER(_NativeV3BatchStats)]
    library.af_v3_batch_safe_steps.restype = c_int


def _configure_v3_session_lifecycle(library, plain):
    library.af_v3_session_create.argtypes = [c_void_p, plain, plain, c_int]
    library.af_v3_session_create.restype = c_void_p
    library.af_v3_session_destroy.argtypes = [c_void_p]
    library.af_v3_session_attach_snapshot.argtypes = [c_void_p, c_void_p, plain, c_int]
    library.af_v3_session_attach_snapshot.restype = c_int
    library.af_v3_session_stats.argtypes = [c_void_p, POINTER(_NativeV3SessionStats)]
    library.af_v3_session_stats.restype = c_int
    library.af_v3_session_ccd_stats.argtypes = [c_void_p, POINTER(_NativeV3CcdStats)]
    library.af_v3_session_ccd_stats.restype = c_int


def _configure_v3_session_collision(library, double, plain):
    pair = POINTER(_NativeContactPair); contacts = POINTER(_NativeWorldContacts)
    library.af_v3_session_contacts.argtypes = [c_void_p, double, c_double, c_double, pair, c_int, contacts]
    library.af_v3_session_contacts.restype = c_int
    library.af_v3_session_copy_contacts.argtypes = [c_void_p, pair, c_int]
    library.af_v3_session_copy_contacts.restype = c_int
    _configure_v3_session_validation(library, double, plain, pair, contacts)
    library.af_v3_session_safe_step.argtypes = [c_void_p, double, double, c_double, c_double,
        c_int, POINTER(_NativeMeshSweep), plain, plain, plain, plain]
    library.af_v3_session_safe_step.restype = c_int


def _configure_v3_session_validation(library, double, plain, pair, contacts):
    batch = POINTER(_NativeWorldBatch)
    library.af_v3_session_validate.argtypes = [c_void_p, double, c_double, c_double,
                                                plain, plain, double, batch]
    library.af_v3_session_validate.restype = c_int
    library.af_v3_session_measure.argtypes = [c_void_p, double, c_double, c_double, c_double,
        pair, c_int, contacts, plain, plain, double, batch]
    library.af_v3_session_measure.restype = c_int


def _configure_v3_session_solver(library, double, integer):
    library.af_v3_session_structural_responses.argtypes = [c_void_p, double, double, double,
        double, integer, double, double, c_int, integer, double, c_int, c_int, double, double,
        POINTER(_NativeBlockResult)]
    library.af_v3_session_structural_responses.restype = c_int


def _configure_block_calls(library, double):
    library.af_block_pentadiagonal_solve.argtypes = [double, double, double, double, c_int,
                                                      double, POINTER(_NativeBlockResult)]
    library.af_block_pentadiagonal_solve.restype = c_int


def _configure_contact_pair_call(library, double, integer, plain):
    library.af_world_query_contact_pairs.argtypes = [c_void_p, double, integer, plain, plain,
                                                      plain, plain, c_int, c_double, c_double,
                                                      POINTER(_NativeContactPair), c_int,
                                                      POINTER(_NativeWorldContacts)]
    library.af_world_query_contact_pairs.restype = c_int


def _configure_contact_solve_call(library, double, integer):
    library.af_contact_block_solve.argtypes = [double, double, double, double, double, integer,
                                                double, double, double, double, c_int, c_double,
                                                integer, double, c_int, c_int, double,
                                                POINTER(_NativeBlockResult)]
    library.af_contact_block_solve.restype = c_int


def _configure_response_call(library, double, integer):
    library.af_structural_contact_responses.argtypes = [double, double, double, double,
        integer, double, double, c_int, integer, double, c_int, c_int, double, double,
        POINTER(_NativeBlockResult)]
    library.af_structural_contact_responses.restype = c_int


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
    _configure_world_updates(library, double, plain)
    _configure_batch_call(library, double, integer, plain)
    _configure_world_queries(library, double, integer, plain)


def _configure_world_updates(library, double, plain):
    library.af_world_update_transform.argtypes = [c_void_p, c_int, double, double]
    library.af_world_update_transform.restype = c_int
    library.af_world_update_vertices.argtypes = [c_void_p, plain, c_int, POINTER(double), plain]
    library.af_world_update_vertices.restype = c_int


def _configure_batch_call(library, double, integer, plain):
    library.af_world_create_batch.argtypes = [POINTER(double), plain, POINTER(integer), plain,
                                               plain, c_int, double, double, plain, plain]
    library.af_world_create_batch.restype = c_void_p


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
    _configure_contact_query(library, double, integer, plain)
    library.af_world_lazy_path.argtypes = [c_void_p, double, c_int, integer, integer, c_int, c_int,
                                            c_double, c_double, c_int, integer, c_int,
                                            POINTER(_NativeWorldSearch)]
    library.af_world_lazy_path.restype = c_int
    _configure_graph_queries(library, double, integer)


def _configure_nearest_query(library, double, plain):
    library.af_world_nearest_points.argtypes = [c_void_p, double, c_int, double, double,
                                                 double, plain, plain]
    library.af_world_nearest_points.restype = c_int


def _configure_contact_query(library, double, integer, plain):
    library.af_world_query_contacts.argtypes = [c_void_p, double, integer, plain, plain, plain,
                                                 plain, c_int,
                                                 c_double, c_double, plain, double, double, double,
                                                 double, plain, POINTER(_NativeWorldContacts)]
    library.af_world_query_contacts.restype = c_int


def _configure_graph_queries(library, double, integer):
    _configure_roadmap_preparation(library, double, integer)
    library.af_graph_shortest_path.argtypes = [double, c_int, integer, integer, c_int, c_int,
                                                integer, c_int, POINTER(_NativeWorldSearch)]
    library.af_graph_shortest_path.restype = c_int
    library.af_mesh_shortest_path.argtypes = [double, c_int, integer, c_int, c_int, c_int,
                                               integer, c_int, POINTER(_NativeWorldSearch)]
    library.af_mesh_shortest_path.restype = c_int


def _configure_roadmap_preparation(library, double, integer):
    library.af_roadmap_neighbors.argtypes = [double, c_int64, c_int64, c_int64,
        integer, integer, c_int64, integer, integer, c_int64]
    library.af_roadmap_neighbors.restype = c_int64
    library.af_roadmap_nearest_batch.argtypes = [double, c_int64, c_int64, c_int64, c_int64, integer]
    library.af_roadmap_nearest_batch.restype = c_int


def native_roadmap_nearest_batch(points, first, count, limit=48):
    values = np.ascontiguousarray(points, dtype=np.float64)
    if values.ndim != 2 or values.shape[1:] != (3,): raise ValueError('invalid nearest-neighbor points')
    k = min(int(limit), len(values)-1)
    if not 0 <= count <= 64 or not 0 <= first <= len(values)-count or k < 0:
        raise ValueError('invalid nearest-neighbor batch')
    output = np.empty((count, k), dtype=np.int64)
    status = load_native().af_roadmap_nearest_batch(_double(values), len(values), first, count, k, _integer(output))
    if status: raise ValueError(f'native nearest-neighbor batch failed: {status}')
    return output


def native_roadmap_neighbors(points, offsets, links, limit=48):
    values, starts, rows = _roadmap_inputs(points, offsets, links)
    old = len(starts) - 1; count = len(values)
    capacity = len(rows) + 2 * (count-old) * (min(limit, count-1) + 2)
    output = np.empty(max(1, capacity), np.int64); indices = np.empty(count+1, np.int64)
    used = load_native().af_roadmap_neighbors(_double(values), count, old, int(limit),
        _integer(starts), _integer(rows), len(rows), _integer(indices), _integer(output), capacity)
    if used < 0: raise ValueError(f"native roadmap preparation failed: {used}")
    return indices, output[:used]


def _roadmap_inputs(points, offsets, links):
    values = np.ascontiguousarray(points, dtype=np.float64)
    starts = np.ascontiguousarray(offsets, dtype=np.int64); rows = np.ascontiguousarray(links, dtype=np.int64)
    if values.ndim != 2 or values.shape[1:] != (3,) or starts.ndim != 1 or rows.ndim != 1:
        raise ValueError("invalid roadmap preparation arrays")
    if not 3 <= len(starts) <= len(values)+1: raise ValueError("invalid original roadmap size")
    return values, starts, rows


def load_native(path=None):
    key = str(_DEFAULT_NATIVE_PATH if path is None else Path(path).resolve())
    if key not in _LIBRARIES:
        _LIBRARIES[key] = _configure(CDLL(key))
    return _LIBRARIES[key]


def native_status(path=None):
    try:
        library = load_native(path)
        version, capabilities = library.af_fiber_ccd_version(), library.af_fiber_ccd_capabilities()
        available = version == V2_NATIVE_ABI and capabilities & V2_NATIVE_CAPABILITIES == V2_NATIVE_CAPABILITIES
        workers = library.af_fiber_worker_threads()
        return available, f"af_fiber_ccd-{version}.{capabilities}.t{workers}", "" if available else "incompatible ABI"
    except (OSError, AttributeError, ValueError) as error:
        return False, "", str(error)


def native_worker_threads(path=None):
    try: return int(load_native(path).af_fiber_worker_threads())
    except (OSError, AttributeError, ValueError): return 1


def native_batch_status(path=None):
    try:
        library = load_native(path); capabilities = library.af_fiber_ccd_capabilities()
        return native_status(path)[0] and bool(capabilities & V2_NATIVE_BATCH_CAPABILITY)
    except (OSError, AttributeError):
        return False


def native_controller_status(path=None):
    try:
        library = load_native(path); capabilities = library.af_fiber_ccd_capabilities()
        required = V3_NATIVE_CONTROLLER_CAPABILITIES
        return native_status(path)[0] and capabilities & required == required
    except (OSError, AttributeError):
        return False


def native_async_controller_status(path=None):
    try:
        library = load_native(path); capabilities = library.af_fiber_ccd_capabilities()
        return native_controller_status(path) and bool(capabilities & V3_NATIVE_ASYNC_CAPABILITY)
    except (OSError, AttributeError):
        return False


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
        self._contact_pair_capacity = 256; self._sessions = 0
        if not self.handle:
            raise RuntimeError("native collision world creation failed")

    @classmethod
    def from_batch(cls, vertices, triangles, owners, matrices=None, path=None):
        value = cls.__new__(cls); value.library = load_native(path)
        value.handle, closed = _create_batch_world(value.library, vertices, triangles,
                                                    owners, matrices)
        value._contact_pair_capacity = 256; value._sessions = 0
        return value, closed

    def add(self, vertices, triangles, owner, collider, closed, matrix=None):
        self._require_mutable_geometry()
        points, faces = _world_mesh(vertices, triangles); transform, inverse = _matrices(matrix)
        args = (self.handle, _double(points), _integer(faces), len(faces), int(owner),
                int(collider), int(bool(closed)), _double(transform), _double(inverse))
        index = self.library.af_world_add_collider(*args)
        if index < 0:
            raise ValueError("invalid native collision-world collider")
        return index

    def commit(self):
        self._require_mutable_geometry()
        if self.library.af_world_commit(self.handle):
            raise RuntimeError("native collision-world commit failed")

    def update_transform(self, index, matrix):
        self._require_mutable_geometry()
        transform, inverse = _matrices(matrix)
        code = self.library.af_world_update_transform(self.handle, int(index),
                                                       _double(transform), _double(inverse))
        if code:
            raise ValueError("invalid native collision-world transform")

    def update_vertices(self, indices, vertices):
        self._require_mutable_geometry()
        rows = tuple(np.ascontiguousarray(value, dtype=np.float64) for value in vertices)
        index = np.ascontiguousarray(indices, dtype=np.int32); counts = _counts(rows)
        if self.library.af_world_update_vertices(self.handle, _plain(index), len(index),
                                                  _double_rows(rows), _plain(counts)):
            raise ValueError("invalid native collision-world vertex batch")

    def _require_mutable_geometry(self):
        if self._sessions:
            raise RuntimeError("native collision geometry is retained by an active session")

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

    def contacts(self, points, edges, first, second, span, threshold, only=None, skip=None):
        values, links, owners = _world_validation_inputs(points, edges, first, second)
        filters = _contact_filters(only, skip, len(links))
        arrays = _contact_arrays(len(links)); result = _NativeWorldContacts()
        args = (self.handle, _double(values), _integer(links), _plain(owners[0]), _plain(owners[1]),
                _plain(filters[0]), _plain(filters[1]),
                len(links), float(span), float(threshold), _plain(arrays[0]), _double(arrays[1]),
                _double(arrays[2]), _double(arrays[3]), _double(arrays[4]), _plain(arrays[5]), byref(result))
        if self.library.af_world_query_contacts(*args):
            raise ValueError("invalid native collision-world contact query")
        return (*arrays, result)

    def contact_pairs(self, points, edges, first, second, span, threshold, only=None, skip=None):
        values, links, owners = _world_validation_inputs(points, edges, first, second)
        filters = _contact_filters(only, skip, len(links))
        base = (self.handle, _double(values), _integer(links), _plain(owners[0]), _plain(owners[1]),
                _plain(filters[0]), _plain(filters[1]), len(links), float(span), float(threshold))
        return self._contact_pair_rows(base)

    def begin_v3_session(self, first, second):
        return NativeV3Session(self, first, second)

    def _contact_pair_rows(self, base):
        capacity = max(1, self._contact_pair_capacity); result = _NativeWorldContacts()
        rows = (_NativeContactPair * capacity)()
        count = self.library.af_world_query_contact_pairs(*base, rows, capacity, byref(result))
        if count == -2: return self._retry_contact_pairs(base, result.active)
        if count < 0: raise ValueError("invalid native all-contact query")
        self._contact_pair_capacity = max(capacity, count)
        return rows[:count], result

    def _retry_contact_pairs(self, base, required):
        capacity = max(1, int(required)); rows = (_NativeContactPair * capacity)()
        result = _NativeWorldContacts()
        count = self.library.af_world_query_contact_pairs(*base, rows, capacity, byref(result))
        if count < 0: raise ValueError("invalid native all-contact query")
        self._contact_pair_capacity = capacity
        return rows[:count], result

    def _contact_pair_count(self, base):
        result = _NativeWorldContacts()
        count = self.library.af_world_query_contact_pairs(*base, None, 0, byref(result))
        if count < 0:
            raise ValueError("invalid native all-contact query")
        return count

    def close(self):
        if self._sessions: raise RuntimeError("cannot close native world with active sessions")
        if self.handle:
            self.library.af_world_destroy(self.handle); self.handle = None

    def __del__(self):
        try:
            self.close()
        except (AttributeError, OSError):
            pass


class NativeV3Session:
    def __init__(self, world, first, second):
        self.world = world; self.library = world.library
        owners = (_owner_array(first), _owner_array(second)); self.edge_count = len(owners[0])
        if len(owners[1]) != self.edge_count: raise ValueError("V3 owner rows must match")
        self.handle = self.library.af_v3_session_create(world.handle, _plain(owners[0]),
                                                        _plain(owners[1]), self.edge_count)
        self._contact_capacity = 256
        if not self.handle: raise RuntimeError("native V3 session creation failed")
        self.world._sessions += 1

    def contacts(self, points, span, threshold):
        values = _v3_points(points, self.edge_count); result = _NativeWorldContacts()
        rows, code = self._contact_call(self.library.af_v3_session_contacts, values,
                                        (float(span), float(threshold)), result)
        self._check_contact_code(code); return rows, result

    def attach_snapshot(self, snapshot, face_owners):
        owners = np.ascontiguousarray(face_owners, dtype=np.int32)
        if self.library.af_v3_session_attach_snapshot(self.handle, snapshot.handle,
                                                       _plain(owners), len(owners)):
            raise ValueError("invalid native V3 triangle snapshot")

    def safe_step(self, source, target, clearance, tolerance, budget):
        first = _v3_points(source, self.edge_count); second = _v3_points(target, self.edge_count)
        result = _NativeMeshSweep(); values = tuple(c_int() for _index in range(4))
        args = (self.handle, _double(first), _double(second), float(clearance), float(tolerance),
                int(budget), byref(result), *(byref(value) for value in values))
        if self.library.af_v3_session_safe_step(*args): raise ValueError("invalid native V3 CCD")
        return result, tuple(value.value for value in values)

    def batch_sweep_input(self, source, target, clearance, tolerance, budget):
        first = _v3_points(source, self.edge_count); second = _v3_points(target, self.edge_count)
        return self, first, second, float(clearance), float(tolerance), int(budget)

    def measure(self, points, span, activation, threshold):
        values = _v3_points(points, self.edge_count); contacts = _NativeWorldContacts()
        arrays = _validation_arrays(self.edge_count); validation = _NativeWorldBatch()
        suffix = (float(span), float(activation), float(threshold))
        rows, code = self._measure_call(values, suffix, contacts, arrays, validation)
        self._check_contact_code(code); return rows, contacts, arrays, validation

    def validate(self, points, span, threshold):
        values = _v3_points(points, self.edge_count); arrays = _validation_arrays(self.edge_count)
        result = _NativeWorldBatch(); args = (self.handle, _double(values), float(span),
            float(threshold), _plain(arrays[0]), _plain(arrays[1]), _double(arrays[2]), byref(result))
        if self.library.af_v3_session_validate(*args): raise ValueError("invalid native V3 validation")
        return arrays, result

    def structural_responses(self, base, rhs, contacts, pins, targets):
        count = self.edge_count + 1; bands = tuple(_scalar_band(value, count) for value in base)
        values = np.ascontiguousarray(rhs, dtype=np.float64); arrays = _response_arrays(contacts)
        pin_rows = np.ascontiguousarray(pins, dtype=np.int64)
        pin_values = np.ascontiguousarray(targets, dtype=np.float64)
        return self._solve_responses(bands, values, arrays, pin_rows, pin_values, count)

    def stats(self):
        result, ccd = _NativeV3SessionStats(), _NativeV3CcdStats()
        if self.library.af_v3_session_stats(self.handle, byref(result)): raise RuntimeError("native V3 stats failed")
        if self.library.af_v3_session_ccd_stats(self.handle, byref(ccd)): raise RuntimeError("native V3 CCD stats failed")
        names = ("measures", "contact_queries", "validations", "structural_solves", "sweeps",
                 "edge_capacity", "contact_capacity", "sweep_capacity")
        ccd_names = ("serial_sweeps", "indexed_sweeps", "indexed_clear", "indexed_fallbacks",
                     "serial_clear", "candidate_pairs", "indexed_pairs", "serial_tests", "serial_intervals")
        output = {name: int(getattr(result, name)) for name in names}
        output.update({name: int(getattr(ccd, name)) for name in ccd_names}); return output

    def close(self):
        if self.handle:
            self.library.af_v3_session_destroy(self.handle); self.handle = None
            self.world._sessions = max(0, self.world._sessions - 1)

    def __del__(self):
        try: self.close()
        except (AttributeError, OSError): pass

    def _contact_call(self, function, values, suffix, result):
        capacity = max(1, self._contact_capacity); rows = (_NativeContactPair * capacity)()
        code = function(self.handle, _double(values), *suffix, rows, capacity, byref(result))
        return self._contact_rows(rows, code, result.active), code

    def _measure_call(self, values, suffix, contacts, arrays, validation):
        capacity = max(1, self._contact_capacity); rows = (_NativeContactPair * capacity)()
        args = (self.handle, _double(values), *suffix, rows, capacity, byref(contacts),
                _plain(arrays[0]), _plain(arrays[1]), _double(arrays[2]), byref(validation))
        code = self.library.af_v3_session_measure(*args)
        return self._contact_rows(rows, code, contacts.active), code

    def _contact_rows(self, rows, code, required):
        if code != -2:
            if code >= 0: self._contact_capacity = max(self._contact_capacity, code)
            return rows[:max(0, code)]
        capacity = max(1, int(required)); output = (_NativeContactPair * capacity)()
        copied = self.library.af_v3_session_copy_contacts(self.handle, output, capacity)
        if copied < 0: raise ValueError("invalid native V3 contact copy")
        self._contact_capacity = capacity; return output[:copied]

    def _check_contact_code(self, code):
        if code < 0 and code != -2: raise ValueError("invalid native V3 contact query")

    def _solve_responses(self, bands, rhs, arrays, pins, targets, count):
        output = np.empty_like(rhs); responses = np.empty((len(arrays[0]), count, 3))
        result = _NativeBlockResult(); args = (self.handle, *(_double(row) for row in bands),
            _double(rhs), _integer(arrays[0]), _double(arrays[1]), _double(arrays[2]), len(arrays[0]),
            _integer(pins), _double(targets), len(pins), count, _double(output), _double(responses), byref(result))
        if self.library.af_v3_session_structural_responses(*args) or not result.valid:
            raise np.linalg.LinAlgError("native V3 structural responses failed")
        return output, responses, _block_result(result)


def _owner_array(values):
    array = np.ascontiguousarray(values, dtype=np.int32)
    if array.ndim != 1 or not len(array): raise ValueError("V3 owner rows must be nonempty")
    return array


def native_batch_safe_steps(jobs):
    rows = tuple(jobs)
    if not rows: return (), _empty_v3_batch_stats()
    prepared = tuple(_v3_batch_row(row) for row in rows)
    values = (_NativeV3BatchSweepJob * len(prepared))(*(row[0] for row in prepared))
    stats = _NativeV3BatchStats(); library = prepared[0][1].library
    if any(row[1].library is not library for row in prepared): raise ValueError("V3 batch libraries must match")
    if library.af_v3_batch_safe_steps(values, len(values), byref(stats)):
        raise ValueError("native V3 batch sweep failed")
    return tuple(_v3_batch_output(row) for row in values), _v3_batch_stats(stats)


def _v3_batch_row(job):
    session, source, target, clearance, tolerance, budget = job
    value = _NativeV3BatchSweepJob(session.handle, _double(source), _double(target),
        clearance, tolerance, budget, 0, 0, 0, -1, -1, 0.0, _NativeMeshSweep())
    value._arrays = source, target
    return value, session


def _v3_batch_output(row):
    if row.status: raise ValueError("native V3 batch sweep item failed")
    return row.result, (row.candidates, row.pairs, row.edge, row.face), float(row.elapsed_ms)


def _v3_batch_stats(value):
    return {"submitted": int(value.submitted), "completed": int(value.completed),
            "workers": int(value.workers), "elapsed_ms": float(value.elapsed_ms)}


def _empty_v3_batch_stats():
    return {"submitted": 0, "completed": 0, "workers": 0, "elapsed_ms": 0.0}


def _v3_points(points, edge_count):
    values = np.ascontiguousarray(points, dtype=np.float64)
    if values.shape != (edge_count + 1, 3) or not np.isfinite(values).all():
        raise ValueError("V3 session points must be finite N-by-3")
    return values


def _validation_arrays(edge_count):
    clear = np.empty(edge_count, dtype=np.int32); blockers = np.empty(edge_count, dtype=np.int32)
    minima = np.empty(edge_count, dtype=np.float64); return clear, blockers, minima


def _world_mesh(vertices, triangles):
    points = np.ascontiguousarray(vertices, dtype=np.float64)
    faces = np.ascontiguousarray(triangles, dtype=np.int64)
    if points.ndim != 2 or points.shape[1:] != (3,) or faces.ndim != 2 or faces.shape[1:] != (3,) or not len(faces):
        raise ValueError("collision-world mesh requires vertices and triangles")
    return points, faces


def _create_batch_world(library, vertices, triangles, owners, matrices):
    points, faces, forward, inverse = _batch_inputs(vertices, triangles, matrices)
    owner_rows = np.ascontiguousarray(owners, dtype=np.int32); closed = np.empty(len(points), dtype=np.int32)
    status = c_int(); rows = (_double_rows(points), _plain(_counts(points)),
                              _integer_rows(faces), _plain(_counts(faces)))
    handle = library.af_world_create_batch(*rows, _plain(owner_rows), len(points), _double(forward),
                                           _double(inverse), _plain(closed), byref(status))
    if not handle or status.value:
        raise ValueError("invalid native batch collision world")
    return handle, tuple(bool(value) for value in closed)


def _batch_inputs(vertices, triangles, matrices):
    rows = tuple(_world_mesh(a, b) for a, b in zip(vertices, triangles))
    transforms = tuple(_matrices(value) for value in tuple(matrices or (None,) * len(rows)))
    if len(transforms) != len(rows):
        raise ValueError("transforms must match collider count")
    points, faces = zip(*rows) if rows else ((), ())
    return points, faces, _matrix_rows(transforms, 0), _matrix_rows(transforms, 1)


def _matrix_rows(rows, index):
    return np.ascontiguousarray([row[index].reshape(16) for row in rows], dtype=np.float64)


def _counts(rows):
    return np.ascontiguousarray([len(row) for row in rows], dtype=np.int32)


def _double_rows(rows):
    return (POINTER(c_double) * len(rows))(*(_double(row) for row in rows))


def _integer_rows(rows):
    return (POINTER(c_int64) * len(rows))(*(_integer(row) for row in rows))


def _contact_arrays(count):
    active = np.empty(count, dtype=np.int32); factors = np.empty(count, dtype=np.float64)
    closest = np.empty((count, 3), dtype=np.float64); normals = np.empty_like(closest)
    distances = np.empty(count, dtype=np.float64); blockers = np.empty(count, dtype=np.int32)
    return active, factors, closest, normals, distances, blockers


def _contact_filters(only, skip, count):
    first = np.zeros(count, dtype=np.int32) if only is None else np.ascontiguousarray(only, dtype=np.int32)
    second = np.zeros(count, dtype=np.int32) if skip is None else np.ascontiguousarray(skip, dtype=np.int32)
    if len(first) != count or len(second) != count:
        raise ValueError("contact filters must match edge count")
    return first, second


def _matrices(matrix):
    transform = np.eye(4) if matrix is None else np.asarray(matrix, dtype=np.float64)
    if transform.shape != (4, 4) or not np.isfinite(transform).all():
        raise ValueError("collision-world transform must be finite 4x4")
    return np.ascontiguousarray(transform), np.ascontiguousarray(np.linalg.inv(transform))


def _plain(array):
    return array.ctypes.data_as(POINTER(c_int))


def native_block_solve(diagonal, lower1, lower2, rhs, path=None):
    blocks = tuple(_block_array(value, len(rhs)) for value in (diagonal, lower1, lower2))
    values = np.ascontiguousarray(rhs, dtype=np.float64); output = np.empty_like(values)
    result = _NativeBlockResult(); library = load_native(path)
    code = library.af_block_pentadiagonal_solve(*(_double(value) for value in blocks),
                                                 _double(values), len(values), _double(output), byref(result))
    if code or not result.valid:
        raise np.linalg.LinAlgError("native block-pentadiagonal factorization failed")
    return output, _block_result(result)


def _block_array(value, count):
    array = np.ascontiguousarray(value, dtype=np.float64)
    if array.shape != (count, 3, 3) or not np.isfinite(array).all():
        raise ValueError("block bands must be finite (N, 3, 3) arrays")
    return array


def native_contact_block_solve(base, rhs, current, contacts, pins, targets, mu, path=None):
    count = len(current); bands = tuple(_scalar_band(value, count) for value in base)
    values = np.ascontiguousarray(rhs, dtype=np.float64); points = np.ascontiguousarray(current, dtype=np.float64)
    edges, factors, normals, gaps, multipliers = _contact_arrays_v3(contacts)
    pin_rows = np.ascontiguousarray(pins, dtype=np.int64); pin_values = np.ascontiguousarray(targets, dtype=np.float64)
    output = np.empty_like(points); result = _NativeBlockResult(); library = load_native(path)
    args = (*(_double(row) for row in bands), _double(values), _double(points), _integer(edges),
            _double(factors), _double(normals), _double(gaps), _double(multipliers), len(edges), float(mu),
            _integer(pin_rows), _double(pin_values), len(pin_rows), count, _double(output), byref(result))
    if library.af_contact_block_solve(*args) or not result.valid:
        raise np.linalg.LinAlgError("native contact block factorization failed")
    return output, _block_result(result)


def native_structural_contact_responses(base, rhs, contacts, pins, targets, path=None):
    count = len(rhs); bands = tuple(_scalar_band(value, count) for value in base)
    values = np.ascontiguousarray(rhs, dtype=np.float64); arrays = _response_arrays(contacts)
    pin_rows = np.ascontiguousarray(pins, dtype=np.int64)
    pin_values = np.ascontiguousarray(targets, dtype=np.float64)
    output = np.empty_like(values); responses = np.empty((len(arrays[0]), count, 3))
    result = _NativeBlockResult(); library = load_native(path)
    args = (*(_double(row) for row in bands), _double(values), _integer(arrays[0]),
        _double(arrays[1]), _double(arrays[2]), len(arrays[0]), _integer(pin_rows),
        _double(pin_values), len(pin_rows), count, _double(output), _double(responses), byref(result))
    if library.af_structural_contact_responses(*args) or not result.valid:
        raise np.linalg.LinAlgError("native structural contact responses failed")
    return output, responses, _block_result(result)


def _response_arrays(contacts):
    rows = tuple(contacts); edges = np.ascontiguousarray([row[0] for row in rows], dtype=np.int64)
    factors = np.ascontiguousarray([row[1] for row in rows], dtype=np.float64)
    normals = np.ascontiguousarray([row[2] for row in rows], dtype=np.float64).reshape((-1, 3))
    return edges, factors, normals


def _contact_arrays_v3(contacts):
    rows = tuple(contacts)
    edges = np.ascontiguousarray([row[0] for row in rows], dtype=np.int64)
    factors = np.ascontiguousarray([row[1] for row in rows], dtype=np.float64)
    normals = np.ascontiguousarray([row[2] for row in rows], dtype=np.float64).reshape((-1, 3))
    gaps = np.ascontiguousarray([row[3] for row in rows], dtype=np.float64)
    multipliers = np.ascontiguousarray([row[4] for row in rows], dtype=np.float64)
    return edges, factors, normals, gaps, multipliers


def _scalar_band(value, count):
    array = np.ascontiguousarray(value, dtype=np.float64)
    if array.shape != (count,) or not np.isfinite(array).all():
        raise ValueError("base bands must be finite N-vectors")
    return array


def _block_result(result):
    return {"condition": float(result.condition), "assembly_ms": float(result.assembly_ms),
            "factor_ms": float(result.factor_ms), "solve_ms": float(result.solve_ms)}


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
    return (output.safe, bool(output.possible), bool(output.valid), output.tested,
            output.intervals, reason, output.limiting)
