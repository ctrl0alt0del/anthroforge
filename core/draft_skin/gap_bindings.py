"""Native batched binding for refined draft skin meshes."""
import ctypes as ct
import numpy as np
from .bindings import empty_skin_bindings, binding_quality
from .gap_native import point_array


def _configure(lib):
    double = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
    integer = np.ctypeslib.ndpointer(dtype=np.int32, flags="C_CONTIGUOUS")
    floating = np.ctypeslib.ndpointer(dtype=np.float32, flags="C_CONTIGUOUS")
    function = lib.af_skin_bind
    function.argtypes = [ct.c_void_p, double, ct.c_int, integer, integer, floating, floating, floating, floating]
    function.restype = ct.c_int
    return function


def bind(vertices, queries, progress=None, cancelled=None):
    from .gap_tiles import _native_call
    from .status import check_cancelled
    function = _configure(queries.lib)
    result = empty_skin_bindings(len(vertices), 4)
    arguments = (queries.handle, point_array(vertices), len(vertices),
        result.source_indices, result.triangle_indices, result.barycentric, result.weights, result.normal_offsets, result.support)
    code = _native_call(queries, arguments, progress, cancelled, function); check_cancelled(cancelled)
    if code:
        raise RuntimeError(f"Native draft-skin binding failed ({code}).")
    present = result.source_indices >= 0
    result.source_indices[present] = queries.source_indices[result.source_indices[present]]
    return result, binding_quality(result)
