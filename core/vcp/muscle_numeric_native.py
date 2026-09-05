"""ctypes bridge for the packed native Muscle numerical backend."""

from ctypes import POINTER, Structure, byref, c_double, c_int, c_int64, c_void_p
from os import environ
from time import perf_counter

import numpy as np

from .muscle_numeric import (MuscleNumericBackend, MuscleNumericBatchResult,
                             MuscleNumericResult, _invalid_result, _readonly_array)
from .v2.collision_native import (MUSCLE_NUMERIC_CAPABILITY, _double, load_native,
                                  native_status)


class _MuscleInput(Structure):
    _fields_ = [(name, c_int) for name in ("point_start", "input_rows", "input_cols",
        "target_cols", "densify", "closed_u", "topology_closed_v", "topology_flip",
        "inflation_mode", "inflation_enabled", "falloff", "inflation_closed_v", "inflation_flip",
        "initialize_control")]
    _fields_ += [(name, c_double) for name in ("amount", "radius", "depth", "b_strength",
                                                "b_band", "b_power", "taper")]
    _fields_ += [("control", c_double * 3)]


class _MuscleStats(Structure):
    _fields_ = [(name, c_int) for name in ("workers", "parallel", "muscles",
                                                   "input_points", "output_points")]
    _fields_ += [("elapsed_ms", c_double)]


def native_muscle_status(path=None):
    try:
        library = load_native(path); capabilities = library.af_fiber_ccd_capabilities()
        return native_status(path)[0] and bool(capabilities & MUSCLE_NUMERIC_CAPABILITY)
    except (AttributeError, OSError, ValueError): return False


def execute_native_muscle_batch(requests, path=None):
    library = load_native(path); _configure(library)
    points, inputs = _pack_requests(requests); stats = _MuscleStats(); started = perf_counter()
    handle = library.af_muscle_batch_create(_double(points), len(points), inputs, len(inputs), byref(stats))
    if not handle: raise RuntimeError("native Muscle batch creation failed")
    try: results = tuple(_copy_result(library, handle, index, row.muscle_id) for index, row in enumerate(requests))
    finally: library.af_muscle_batch_destroy(handle)
    elapsed = (perf_counter() - started) * 1000.0
    return MuscleNumericBatchResult(results, MuscleNumericBackend.NATIVE.value,
                                    elapsed, int(stats.workers), bool(stats.parallel))


def _configure(library):
    if getattr(library, "_af_muscle_configured", False): return
    library.af_muscle_batch_create.argtypes = [POINTER(c_double), c_int, POINTER(_MuscleInput), c_int, POINTER(_MuscleStats)]
    library.af_muscle_batch_create.restype = c_void_p
    library.af_muscle_batch_info.argtypes = [c_void_p, c_int, POINTER(c_int), POINTER(c_int), POINTER(c_int), POINTER(c_int)]
    library.af_muscle_batch_info.restype = c_int; _configure_copy(library)
    library.af_muscle_set_parallel_threshold.argtypes = [c_int]
    library.af_muscle_set_parallel_threshold.restype = c_int
    library.af_muscle_set_parallel_threshold(_parallel_threshold())
    library._af_muscle_configured = True


def _configure_copy(library):
    library.af_muscle_batch_copy.argtypes = [c_void_p, c_int, POINTER(c_double),
                                              POINTER(c_double), POINTER(c_int64)]
    library.af_muscle_batch_copy.restype = c_int
    library.af_muscle_batch_destroy.argtypes = [c_void_p]


def _parallel_threshold():
    raw = environ.get("AF_MUSCLE_NATIVE_PARALLEL_POINTS", "1024").strip()
    try: value = int(raw)
    except ValueError as error: raise ValueError("AF_MUSCLE_NATIVE_PARALLEL_POINTS must be an integer") from error
    if value < 0: raise ValueError("AF_MUSCLE_NATIVE_PARALLEL_POINTS must be nonnegative")
    return value


def _pack_requests(requests):
    arrays = tuple(np.asarray(row.points, dtype=np.float64).reshape((-1, 3)) for row in requests)
    points = np.ascontiguousarray(np.concatenate(arrays) if arrays else np.zeros((1, 3)))
    inputs = (_MuscleInput * len(requests))(); offset = 0
    for index, (request, array) in enumerate(zip(requests, arrays)):
        inputs[index] = _input_row(request, offset); offset += len(array)
    return points, inputs


def _input_row(request, offset):
    spec, shape = request.spec, request.points.shape
    ints = (offset, shape[0], shape[1], spec.target_count, int(spec.densify), int(spec.closed_u),
            int(spec.close_across_fibers), int(spec.topology_flip_normals),
            int(spec.inflation_mode == "DISTRIBUTED"), int(spec.inflation_enabled),
            _falloff(spec.inflation_falloff_type), int(spec.closed_v), int(spec.flip_normals),
            int(spec.initialize_control))
    floats = (spec.inflation_max_value, spec.inflation_falloff_radius,
              spec.inflation_direction_depth, spec.inflation_boundary_strength,
              spec.inflation_boundary_band, spec.inflation_boundary_power,
              spec.inflation_length_taper_band)
    row = _MuscleInput(*ints, *floats); row.control[:] = spec.control_world
    return row


def _falloff(value):
    return {"GAUSSIAN": 0, "LINEAR": 1, "SMOOTHSTEP": 2}.get(str(value), 0)


def _copy_result(library, handle, index, muscle_id):
    rows, cols, faces, status = c_int(), c_int(), c_int(), c_int()
    code = library.af_muscle_batch_info(handle, index, byref(rows), byref(cols), byref(faces), byref(status))
    if code or status.value: return _invalid_result(muscle_id, f"native Muscle status {status.value or code}")
    base = np.empty((rows.value * cols.value, 3), dtype=np.float64)
    inflated, topology = np.empty_like(base), np.empty((faces.value, 4), dtype=np.int64)
    if library.af_muscle_batch_copy(handle, index, _double(base), _double(inflated), _integer(topology)):
        return _invalid_result(muscle_id, "native Muscle result copy failed")
    return _native_result(muscle_id, base, inflated, topology, rows.value, cols.value)


def _integer(array):
    return array.ctypes.data_as(POINTER(c_int64))


def _native_result(muscle_id, base, inflated, faces, rows, cols):
    return MuscleNumericResult(str(muscle_id), _readonly_array(base, np.float64, (-1, 3)),
        _readonly_array(inflated, np.float64, (-1, 3)), _readonly_array(faces, np.int64, (-1, 4)),
        int(rows), int(cols))
