"""Bounded-memory native mesh validation and original-source coverage."""
import ctypes as ct
import numpy as np
from .gap_native import library, point_array, face_array
from .model import SkinValidationReport


def _configure(lib):
    double = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
    integer = np.ctypeslib.ndpointer(dtype=np.int64, flags="C_CONTIGUOUS")
    lib.af_skin_mesh_quality.argtypes = [double, ct.c_int, integer, ct.c_int, double]
    lib.af_skin_source_coverage.argtypes = [ct.c_void_p, double, ct.c_int, integer, ct.c_int, ct.c_double, double]
    lib.af_skin_validate_gap_points.argtypes = [double, ct.c_int, integer, ct.c_int, double, ct.c_int, double]


def validate_gap_points(vertices, faces, points):
    """Rows are distance, buried-point violation, numerical boundary tolerance."""
    lib = library(); _configure(lib); vertices = point_array(vertices)
    faces = face_array(faces, len(vertices)); points = point_array(points)
    rows = np.empty((len(points), 3), dtype=np.float64)
    if lib.af_skin_validate_gap_points(vertices, len(vertices), faces, len(faces), points, len(points), rows):
        raise ValueError('Cannot validate protected-gap sample points.')
    return rows


def validate(vertices, faces, source_inside=True):
    lib = library(); _configure(lib); vertices = point_array(vertices)
    faces = face_array(faces, len(vertices)); values = np.zeros(9, dtype=np.float64)
    if lib.af_skin_mesh_quality(vertices, len(vertices), faces, len(faces), values):
        raise ValueError("Native draft-skin mesh validation failed.")
    checks = dict(finite=bool(values[0]), connected=bool(values[1] == 1), watertight=bool(values[2]),
                  orientable=bool(values[3]), positive_volume=bool(values[4]), no_degenerates=bool(values[5]),
                  source_inside=bool(source_inside))
    failed = [name for name, valid in checks.items() if not valid and name != "connected"]
    report = SkinValidationReport(not failed, **checks, message="Validation failed: "+", ".join(failed) if failed else "")
    return report, {"components": int(values[1]), "minimum_triangle_area2": float(values[6]), "volume": float(values[7])}


def source_coverage(vertices, faces, queries, tolerance):
    lib = queries.lib; _configure(lib); vertices = point_array(vertices)
    faces = face_array(faces, len(vertices)); values = np.zeros(4, dtype=np.float64)
    code = lib.af_skin_source_coverage(queries.handle, vertices, len(vertices), faces, len(faces), tolerance, values)
    if code:
        raise ValueError("Native source coverage validation failed.")
    return {"source_vertices_outside": int(values[0]), "source_triangles_crossed": int(values[1]),
            "source_vertices_checked": int(values[2]), "source_triangles_checked": int(values[3])}


def source_intersections(queries, progress=None, cancelled=None):
    from .gap_tiles import _native_call
    from .status import check_cancelled
    function = queries.lib.af_skin_source_intersections
    function.argtypes = [ct.c_void_p, ct.POINTER(ct.c_int64)]
    count = ct.c_int64()
    code = _native_call(queries, (queries.handle, ct.byref(count)), progress, cancelled, function)
    check_cancelled(cancelled)
    if code:
        raise ValueError('Cannot check original-source intersections.')
    return {'preexisting_source_intersections': count.value}


def supported_components(vertices, faces, queries):
    function = queries.lib.af_skin_supported_components
    double = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
    index = np.ctypeslib.ndpointer(dtype=np.int64, flags="C_CONTIGUOUS")
    byte = np.ctypeslib.ndpointer(dtype=np.uint8, flags="C_CONTIGUOUS")
    integer = np.ctypeslib.ndpointer(dtype=np.int32, flags="C_CONTIGUOUS")
    function.argtypes = [ct.c_void_p, double, ct.c_int, index, ct.c_int, byte, integer]
    vertices = point_array(vertices); faces = face_array(faces, len(vertices))
    keep = np.empty(len(vertices), np.uint8); stats = np.zeros(3, np.int32)
    if function(queries.handle, vertices, len(vertices), faces, len(faces), keep, stats):
        raise ValueError("Cannot validate draft-skin component support.")
    selected = keep.astype(bool); remap = np.cumsum(selected, dtype=np.int32)-1
    return vertices[selected].astype(np.float32), remap[faces[selected[faces[:, 0]]]], int(stats[1])
