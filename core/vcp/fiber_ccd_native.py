from ctypes import CDLL, POINTER, Structure, byref, c_double, c_int, c_int64
from pathlib import Path

import numpy as np

from .fiber_ccd_reference import (
    MeshSweepResult,
    PrimitiveSweepResult,
    _candidate_faces,
    _mesh_inputs,
)


class _NativeSweep(Structure):
    _fields_ = [(name, c_double) for name in ("safe", "upper", "clearance", "minimum")]
    _fields_ += [(name, c_int) for name in ("possible", "valid", "intervals", "reason")]


class _NativeMeshSweep(Structure):
    _fields_ = [("safe", c_double)]
    _fields_ += [(name, c_int) for name in ("possible", "valid", "tested", "intervals", "reason")]


_REASONS = ("CLEAR", "AABB_CLEAR", "INVALID_START", "POSSIBLE_COLLISION", "BUDGET_EXHAUSTED")
_LIBRARY = None


class _MeshState:
    def __init__(self):
        self.safe, self.possible, self.valid = 1.0, False, True
        self.candidates, self.tested, self.intervals = 0, 0, 0


def _library_path():
    return Path(__file__).resolve().parents[2] / "native" / "fiber_ccd" / "af_fiber_ccd.dll"


def _configure(library):
    pointer = POINTER(c_double)
    library.af_swept_segment_triangle.argtypes = [pointer, pointer, pointer, c_double, c_double, c_int, POINTER(_NativeSweep)]
    library.af_swept_segment_triangle.restype = c_int
    library.af_mesh_pair_safe_step.argtypes = [pointer, pointer, pointer, c_int, c_double, c_double, c_int, POINTER(_NativeMeshSweep)]
    library.af_mesh_pair_safe_step.restype = c_int
    library.af_candidate_pairs.argtypes = [pointer, pointer, POINTER(c_int64), c_int, pointer,
                                           POINTER(c_int64), c_int, c_double, POINTER(c_int64)]
    library.af_candidate_pairs.restype = c_int
    return library


def native_library():
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = _configure(CDLL(str(_library_path())))
    return _LIBRARY


def native_available():
    try:
        return native_library().af_fiber_ccd_version() == 1
    except (OSError, AttributeError):
        return False


def _array(value, shape, name):
    result = np.ascontiguousarray(value, dtype=np.float64)
    if result.shape != shape or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must have finite shape {shape}")
    return result


def _call(start, end, triangle, clearance, tolerance, budget):
    output, pointer = _NativeSweep(), POINTER(c_double)
    values = [item.ctypes.data_as(pointer) for item in (start, end, triangle)]
    code = native_library().af_swept_segment_triangle(*values, clearance, tolerance, budget, byref(output))
    if code:
        raise ValueError("invalid native CCD arguments")
    return output


def swept_segment_triangle_native(start, end, triangle, clearance=0.0, time_tolerance=1.0e-5, max_intervals=262143):
    start = _array(start, (2, 3), "start")
    end = _array(end, (2, 3), "end")
    triangle = _array(triangle, (3, 3), "triangle")
    output = _call(start, end, triangle, float(clearance), float(time_tolerance), int(max_intervals))
    reason = _REASONS[output.reason] if 0 <= output.reason < len(_REASONS) else "ERROR"
    return PrimitiveSweepResult(output.safe, output.upper, output.clearance, output.minimum,
                                bool(output.possible), bool(output.valid), output.intervals, reason)


def _absorb(state, result):
    state.tested += 1
    state.intervals += result.intervals
    state.valid = state.valid and result.initially_valid
    state.possible = state.possible or result.possible_collision
    state.safe *= result.safe_step


def _sweep_edge(state, edge_index, edge, data, clearance, pair_filter):
    start, end, triangle_vertices, bounds, padding = data
    scaled = start[edge] + state.safe * (end[edge] - start[edge])
    candidates = _candidate_faces(start[edge], scaled, bounds, padding)
    state.candidates += len(candidates)
    for triangle_index in candidates:
        if pair_filter and not pair_filter(edge_index, int(triangle_index)):
            continue
        result = swept_segment_triangle_native(start[edge], scaled, triangle_vertices[triangle_index], clearance)
        _absorb(state, result)
        if not state.valid or state.safe == 0.0:
            return False
        scaled = start[edge] + state.safe * (end[edge] - start[edge])
    return True


def _mesh_result(state):
    reason = "INVALID_START" if not state.valid else "POSSIBLE_COLLISION" if state.possible else "CLEAR"
    return MeshSweepResult(state.safe, state.possible, state.valid, state.candidates,
                           state.tested, state.intervals, reason)


def _candidate_indices(start, end, edges, vertices, triangles, padding):
    library, double, integer = native_library(), POINTER(c_double), POINTER(c_int64)
    args = [start.ctypes.data_as(double), end.ctypes.data_as(double), edges.ctypes.data_as(integer), len(edges),
            vertices.ctypes.data_as(double), triangles.ctypes.data_as(integer), len(triangles), padding]
    count = library.af_candidate_pairs(*args, None)
    output = np.empty((count, 2), dtype=np.int64)
    library.af_candidate_pairs(*args, output.ctypes.data_as(integer))
    return output


def _candidate_batch(start, end, edges, triangle_vertices, candidates, pair_filter):
    allowed = [(int(edge), int(face)) for edge, face in candidates
               if pair_filter is None or pair_filter(int(edge), int(face))]
    if not allowed:
        return [np.empty((0, 2, 3)), np.empty((0, 2, 3)), np.empty((0, 3, 3))]
    edge_ids, face_ids = np.asarray(allowed, dtype=np.int64).T
    edge_vertices = edges[edge_ids]
    return [np.ascontiguousarray(start[edge_vertices]), np.ascontiguousarray(end[edge_vertices]),
            np.ascontiguousarray(triangle_vertices[face_ids])]


def _call_mesh(arrays, clearance):
    output, pointer = _NativeMeshSweep(), POINTER(c_double)
    values = [item.ctypes.data_as(pointer) for item in arrays]
    code = native_library().af_mesh_pair_safe_step(*values, len(arrays[0]), clearance, 1.0e-5, 262143, byref(output))
    if code:
        raise ValueError("invalid native mesh CCD arguments")
    return output


def _native_mesh_result(output, candidates):
    reason = _REASONS[output.reason] if 0 <= output.reason < len(_REASONS) else "ERROR"
    return MeshSweepResult(output.safe, bool(output.possible), bool(output.valid), candidates,
                           output.tested, output.intervals, reason)


def candidate_pairs_native(start_points, end_points, edges, vertices, triangles, clearance=0.0):
    start, end, edges, vertices, triangles = _mesh_inputs(start_points, end_points, edges, vertices, triangles)
    edges, triangles = np.ascontiguousarray(edges, dtype=np.int64), np.ascontiguousarray(triangles, dtype=np.int64)
    scale = max(1.0, float(np.max(np.abs(start), initial=0.0)), float(np.max(np.abs(end), initial=0.0)), float(np.max(np.abs(vertices), initial=0.0)))
    padding = float(clearance) + 128.0 * np.finfo(np.float64).eps * scale
    return _candidate_indices(start, end, edges, vertices, triangles, padding)


def pair_collision_free_step_native(starts, ends, triangles, clearance=0.0):
    starts = np.ascontiguousarray(starts, dtype=np.float64).reshape((-1, 2, 3))
    ends = np.ascontiguousarray(ends, dtype=np.float64).reshape((-1, 2, 3))
    triangles = np.ascontiguousarray(triangles, dtype=np.float64).reshape((-1, 3, 3))
    if not (len(starts) == len(ends) == len(triangles)):
        raise ValueError(f"native CCD pair arrays must have equal length: {len(starts)}, {len(ends)}, {len(triangles)}")
    if not len(starts):
        return MeshSweepResult(1.0, False, True, 0, 0, 0, "CLEAR")
    return _native_mesh_result(_call_mesh((starts, ends, triangles), float(clearance)), len(starts))


def mesh_collision_free_step_native(start_points, end_points, edges, vertices, triangles, clearance=0.0, pair_filter=None):
    start, end, edges, vertices, triangles = _mesh_inputs(start_points, end_points, edges, vertices, triangles)
    edges, triangles = np.ascontiguousarray(edges, dtype=np.int64), np.ascontiguousarray(triangles, dtype=np.int64)
    triangle_vertices = vertices[triangles]
    scale = max(1.0, float(np.max(np.abs(start), initial=0.0)), float(np.max(np.abs(end), initial=0.0)), float(np.max(np.abs(vertices), initial=0.0)))
    padding = float(clearance) + 128.0 * np.finfo(np.float64).eps * scale
    candidate_ids = _candidate_indices(start, end, edges, vertices, triangles, padding)
    arrays = _candidate_batch(start, end, edges, triangle_vertices, candidate_ids, pair_filter)
    if not len(arrays[0]):
        return MeshSweepResult(1.0, False, True, len(candidate_ids), 0, 0, "CLEAR")
    return _native_mesh_result(_call_mesh(arrays, float(clearance)), len(candidate_ids))
