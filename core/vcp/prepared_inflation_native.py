"""Prepared-grid native entry point; legacy packed request ABI remains unchanged."""
from ctypes import POINTER, byref, c_double, c_void_p
import numpy as np
from .muscle_numeric import make_muscle_request
from .muscle_numeric_native import _MuscleInput, _configure, _copy_result, _input_row
from .v2.collision_native import load_native, _double


def inflate_native(grid, spec, edge, fade):
    library = load_native()
    _configure(library)
    if not hasattr(library, "af_muscle_prepared_create"):
        raise RuntimeError("Native library needs rebuild: prepared Muscle grids are unavailable")
    method = library.af_muscle_prepared_create
    method.argtypes = [POINTER(c_double), POINTER(_MuscleInput), POINTER(c_double), POINTER(c_double)]
    method.restype = c_void_p
    request = make_muscle_request("prepared", grid, spec)
    packed = _input_row(request, 0)
    handle = method(_double(request.points), byref(packed), _double(edge), _double(fade))
    if not handle:
        raise RuntimeError("Invalid prepared Muscle input")
    return _read_prepared(library, handle, grid.shape)


def _read_prepared(library, handle, shape):
    try:
        result = _copy_result(library, handle, 0, "prepared")
        if result.error:
            raise RuntimeError(result.error)
        return np.array(result.inflated_vertices.reshape(shape), copy=True)
    finally:
        library.af_muscle_batch_destroy(handle)
