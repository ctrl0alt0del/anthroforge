"""Private ctypes binding for the packaged Fiber V2 collision DLL."""

from ctypes import CDLL, POINTER, Structure, byref, c_double, c_int, c_int64, c_void_p
from pathlib import Path

import numpy as np


V2_NATIVE_ABI = 1
V2_NATIVE_CAPABILITIES = 7


class _NativeMeshSweep(Structure):
    _fields_ = [("safe", c_double)]
    _fields_ += [(name, c_int) for name in ("possible", "valid", "tested", "intervals", "reason")]


_REASONS = ("CLEAR", "AABB_CLEAR", "INVALID_START", "POSSIBLE_COLLISION", "BUDGET_EXHAUSTED")
_LIBRARIES = {}


def native_path():
    return Path(__file__).resolve().parents[3] / "native" / "fiber_ccd" / "af_fiber_ccd.dll"


def clear_native_libraries():
    _LIBRARIES.clear()


def _configure(library):
    _configure_collision_calls(library)
    _configure_snapshot_calls(library)
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


def native_inside(points, vertices, triangles, path=None):
    output = np.empty(len(points), dtype=np.int32)
    args = (_double(points), len(points), _double(vertices), _integer(triangles),
            len(triangles), output.ctypes.data_as(POINTER(c_int)))
    if load_native(path).af_points_inside_closed_mesh(*args):
        raise ValueError("invalid native containment arguments")
    return output.astype(bool)


def native_safe_step(starts, ends, triangles, clearance, tolerance, budget, path=None):
    output = _NativeMeshSweep()
    args = (_double(starts), _double(ends), _double(triangles), len(starts), float(clearance),
            float(tolerance), int(budget), byref(output))
    if load_native(path).af_mesh_pair_safe_step(*args):
        raise ValueError("invalid native CCD arguments")
    reason = _REASONS[output.reason] if 0 <= output.reason < len(_REASONS) else "ERROR"
    return output.safe, bool(output.possible), bool(output.valid), output.tested, output.intervals, reason
