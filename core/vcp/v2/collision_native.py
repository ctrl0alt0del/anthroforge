"""Private ctypes binding for the packaged Fiber V2 collision DLL."""

from ctypes import CDLL, POINTER, Structure, byref, c_double, c_int, c_int64, c_void_p
from pathlib import Path

import numpy as np


V2_NATIVE_ABI = 3
V2_NATIVE_CAPABILITIES = 8191
V2_NATIVE_BATCH_CAPABILITY = 1024


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


_REASONS = ("CLEAR", "AABB_CLEAR", "INVALID_START", "POSSIBLE_COLLISION", "BUDGET_EXHAUSTED")
_LIBRARIES = {}


def native_path():
    return Path(__file__).resolve().parents[3] / "native" / "fiber_ccd" / "af_fiber_ccd_v3.dll"


def clear_native_libraries():
    _LIBRARIES.clear()


def _configure(library):
    _configure_collision_calls(library)
    _configure_snapshot_calls(library)
    _configure_world_calls(library)
    _configure_v3_calls(library)
    return library


def _configure_v3_calls(library):
    double, integer, plain = POINTER(c_double), POINTER(c_int64), POINTER(c_int)
    _configure_block_calls(library, double)
    _configure_contact_pair_call(library, double, integer, plain)
    _configure_contact_solve_call(library, double, integer)
    _configure_response_call(library, double, integer)


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
    library.af_world_update_transform.argtypes = [c_void_p, c_int, double, double]
    library.af_world_update_transform.restype = c_int
    _configure_batch_call(library, double, integer, plain)
    _configure_world_queries(library, double, integer, plain)


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


def native_batch_status(path=None):
    try:
        library = load_native(path); capabilities = library.af_fiber_ccd_capabilities()
        return native_status(path)[0] and bool(capabilities & V2_NATIVE_BATCH_CAPABILITY)
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
        if not self.handle:
            raise RuntimeError("native collision world creation failed")

    @classmethod
    def from_batch(cls, vertices, triangles, owners, matrices=None, path=None):
        value = cls.__new__(cls); value.library = load_native(path)
        value.handle, closed = _create_batch_world(value.library, vertices, triangles,
                                                    owners, matrices)
        return value, closed

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
        count = self._contact_pair_count(base)
        rows = (_NativeContactPair * count)(); result = _NativeWorldContacts()
        if self.library.af_world_query_contact_pairs(*base, rows, count, byref(result)) < 0:
            raise ValueError("invalid native all-contact query")
        return rows, result

    def _contact_pair_count(self, base):
        result = _NativeWorldContacts()
        count = self.library.af_world_query_contact_pairs(*base, None, 0, byref(result))
        if count < 0:
            raise ValueError("invalid native all-contact query")
        return count

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
