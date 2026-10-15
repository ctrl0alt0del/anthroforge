"""Sparse native field tiles on a shared lattice; Python orchestrates meshing."""
import ctypes as ct
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import numpy as np
from skimage.measure import marching_cubes
from .status import check_cancelled, report
from .gap_native import point_array, face_array


def _configure(lib):
    floating = np.ctypeslib.ndpointer(dtype=np.float32, flags="C_CONTIGUOUS")
    integer = np.ctypeslib.ndpointer(dtype=np.int32, flags="C_CONTIGUOUS")
    double = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
    lib.af_skin_tiles_create.argtypes = [ct.c_void_p, floating, integer, double, integer, double,
                                       ct.c_double, ct.c_double, ct.c_uint64]
    lib.af_skin_tiles_create.restype = ct.c_void_p
    lib.af_skin_tiles_destroy.argtypes = [ct.c_void_p]
    lib.af_skin_tiles_count.argtypes = [ct.c_void_p]
    lib.af_skin_tiles_copy_range.argtypes = [ct.c_void_p, ct.c_int, ct.c_int, integer, floating]
    lib.af_skin_tiles_sample.argtypes = [ct.c_void_p, double, ct.c_int, double]
    lib.af_skin_gap_progress.argtypes = [ct.c_void_p, integer]
    lib.af_skin_gap_error.argtypes = [ct.c_void_p]
    lib.af_skin_gap_error.restype = ct.c_char_p
    _configure_validation(lib, double)


def _configure_validation(lib, double):
    lib.af_skin_gap_cancel.argtypes = [ct.c_void_p]
    lib.af_skin_tiles_release_field.argtypes = [ct.c_void_p]
    integer = np.ctypeslib.ndpointer(dtype=np.int64, flags="C_CONTIGUOUS")
    lib.af_skin_tiles_validate.argtypes = [ct.c_void_p, double, ct.c_int, integer, ct.c_int, double]
    lib.af_skin_tiles_statistics.argtypes = [ct.c_void_p, double]
    if hasattr(lib, 'af_skin_tiles_memory_statistics'):
        lib.af_skin_tiles_memory_statistics.argtypes = [ct.c_void_p, double]
    lib.af_skin_gap_precision.argtypes = [ct.c_void_p, ct.c_double, double]
    floating = np.ctypeslib.ndpointer(dtype=np.float32, flags="C_CONTIGUOUS")
    shape = np.ctypeslib.ndpointer(dtype=np.int32, flags="C_CONTIGUOUS")
    lib.af_skin_gap_precision_field.argtypes = [ct.c_void_p, floating, shape, double, ct.c_double, double]


def _native_call(queries, arguments, progress, cancelled, function=None):
    check_cancelled(cancelled)
    with ThreadPoolExecutor(max_workers=1) as pool:
        target = queries.lib.af_skin_tiles_create if function is None else function
        arguments = (queries.handle, *arguments) if function is None else arguments
        future = pool.submit(target, *arguments)
        while True:
            try:
                return future.result(timeout=0.5)
            except TimeoutError:
                _poll(queries, progress, cancelled)


def _poll(queries, progress, cancelled):
    if cancelled and cancelled():
        queries.lib.af_skin_gap_cancel(queries.handle)
    state = np.zeros(3, dtype=np.int32)
    queries.lib.af_skin_gap_progress(queries.handle, state)
    names = {0: "Checking gap precision", 1: "Measuring original gaps", 2: "Classifying exterior space",
             3: "Building gap constraints", 4: "Evaluating protected skin", 6: "Smoothing within constraints"}
    fraction = float(state[1]) / max(1, int(state[2]))
    report(progress, "Local gaps", 0.78 + 0.1 * fraction, names.get(int(state[0]), "Preparing native tiles"))


class SkinTiles:
    def __init__(self, queries, field, origin, voxel, grid, reach, offset, budget, progress=None, cancelled=None):
        self.queries = queries; self.lib = queries.lib; _configure(self.lib)
        self.origin, self.shape, self.voxel = grid
        self.budget = int(budget)
        arguments = (np.ascontiguousarray(field, dtype=np.float32), np.asarray(field.shape, np.int32),
            np.asarray([*origin, voxel], np.float64), np.asarray(self.shape, np.int32),
            np.asarray([*self.origin, self.voxel], np.float64), reach, offset, budget)
        self.handle = _native_call(queries, arguments, progress, cancelled)
        if not self.handle:
            check_cancelled(cancelled)
            raise RuntimeError(self.lib.af_skin_gap_error(queries.handle).decode("utf-8", errors="replace"))
        if cancelled and cancelled():
            self.close(); check_cancelled(cancelled)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        if self.handle:
            self.lib.af_skin_tiles_destroy(self.handle); self.handle = None

    def fields(self, first=0, count=None):
        count = self.lib.af_skin_tiles_count(self.handle)-first if count is None else count
        starts = np.empty((count, 3), dtype=np.int32)
        values = np.empty((count, 33, 33, 33), dtype=np.float32)
        if self.lib.af_skin_tiles_copy_range(self.handle, first, count, starts, values):
            raise RuntimeError("Cannot read native draft-skin surface tiles.")
        return starts, values

    def field_batches(self):
        count = self.lib.af_skin_tiles_count(self.handle)
        for first in range(0, count, 32):
            starts, fields = self.fields(first, min(32, count-first))
            yield from zip(starts, fields)

    def release_field(self):
        self.lib.af_skin_tiles_release_field(self.handle)

    def constraints(self):
        function = self.lib.af_skin_tiles_constraints
        function.argtypes = [ct.c_void_p, np.ctypeslib.ndpointer(dtype=np.float64, flags='C_CONTIGUOUS')]
        rows = np.empty((int(self.statistics()['gap_constraints']), 12), dtype=np.float64)
        if function(self.handle, rows):
            raise ValueError('Cannot read native gap constraint diagnostics.')
        return rows

    def sample(self, points):
        points = point_array(points); output = np.empty(len(points), dtype=np.float64)
        if self.lib.af_skin_tiles_sample(self.handle, points, len(points), output):
            raise RuntimeError("Cannot sample native draft-skin tiles.")
        return output

    def smooth(self, vertices, faces, iterations=8, progress=None, cancelled=None):
        floating = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
        integer = np.ctypeslib.ndpointer(dtype=np.int64, flags="C_CONTIGUOUS")
        function = self.lib.af_skin_tiles_finish
        function.argtypes = [ct.c_void_p, floating, ct.c_int, integer, ct.c_int, ct.c_int]
        vertices = point_array(vertices); faces = face_array(faces, len(vertices))
        args = (self.handle, vertices, len(vertices), faces, len(faces), iterations)
        code = _native_call(self.queries, args, progress, cancelled, function)
        check_cancelled(cancelled)
        if code:
            raise ValueError(self.lib.af_skin_gap_error(self.queries.handle).decode())
        return vertices.astype(np.float32)

    def validation(self, vertices, faces, progress=None, cancelled=None):
        vertices = point_array(vertices); faces = face_array(faces, len(vertices))
        result = np.zeros(7, dtype=np.float64)
        arguments = (self.handle, vertices, len(vertices), faces, len(faces), result)
        code = _native_call(self.queries, arguments, progress, cancelled, self.lib.af_skin_tiles_validate)
        check_cancelled(cancelled)
        if code:
            raise ValueError("Native final-skin gap validation failed.")
        names = ("source_vertices_outside", "source_triangles_crossed", "source_vertices_checked",
                 "source_triangles_checked", "protected_gap_checks", "protected_gap_violations", "minimum_gap_clearance")
        return dict(zip(names, map(float, result)), gap_validation_policy='contact-permitted-v2')

    def statistics(self):
        result = np.zeros(8, dtype=np.float64)
        if self.lib.af_skin_tiles_statistics(self.handle, result):
            raise ValueError("Cannot read native gap statistics.")
        names = ("allocated_tiles", "surface_tiles", "allocated_samples", "stored_field_bytes", "gap_constraints",
                 "smallest_protected_gap", "protected_constraints", "dense_equivalent_samples")
        return dict(zip(names, map(float, result)), field_budget_bytes=self.budget, **self.memory_statistics())

    def memory_statistics(self):
        function = getattr(self.lib, 'af_skin_tiles_memory_statistics', None)
        if function is None:
            return {}
        result = np.zeros(6, dtype=np.float64)
        if function(self.handle, result):
            raise ValueError('Cannot read native field memory statistics.')
        names = ('resident_field_bytes', 'peak_field_bytes', 'estimated_peak_native_bytes',
                 'initial_tiles', 'propagation_tiles', 'auxiliary_storage_bytes')
        return dict(zip(names, map(float, result)))

    def mesh(self, cancelled=None):
        vertices, faces, offset = [], [], 0
        for start, field in self.field_batches():
            check_cancelled(cancelled)
            points, triangles, _, _ = marching_cubes(field, 0, allow_degenerate=False)
            vertices.append(points.astype(np.float64) + start)
            faces.append(triangles.astype(np.int32) + offset); offset += len(points)
        if not vertices:
            raise ValueError("Draft skin has no resolved surface.")
        points, triangles = _stitch(np.concatenate(vertices), np.concatenate(faces))
        return (points*self.voxel + self.origin).astype(np.float32), triangles


def precision(queries, reach, progress=None, cancelled=None):
    _configure(queries.lib); result = np.zeros(2, dtype=np.float64)
    arguments = (queries.handle, reach, result)
    code = _native_call(queries, arguments, progress, cancelled, queries.lib.af_skin_gap_precision)
    check_cancelled(cancelled)
    if code:
        raise ValueError("Cannot determine the precision needed to preserve draft-skin gaps.")
    return float(result[0]), int(result[1])


def exterior_precision(queries, field, origin, voxel, reach, progress=None, cancelled=None):
    _configure(queries.lib); result = np.zeros(2, dtype=np.float64)
    arguments = (queries.handle, np.ascontiguousarray(field, dtype=np.float32),
                 np.asarray(field.shape, np.int32), np.asarray([*origin, voxel], np.float64), reach, result)
    code = _native_call(queries, arguments, progress, cancelled, queries.lib.af_skin_gap_precision_field)
    check_cancelled(cancelled)
    if code:
        raise ValueError("Cannot determine the precision needed to preserve exterior draft-skin gaps.")
    return float(result[0]), int(result[1])


def _stitch(vertices, faces):
    keys = np.round(vertices, 5)
    _, first, remap = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    triangles = remap[faces].astype(np.int32)
    return vertices[first], triangles
