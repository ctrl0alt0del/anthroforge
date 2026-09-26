"""Versioned native surface-profile evaluation and two-side composition."""
from ctypes import POINTER, c_double, c_int, c_int64
import numpy as np
from .v2.collision_native import load_native, _double


def library():
    lib = load_native()
    if not hasattr(lib, 'af_muscle_envelope_version') or lib.af_muscle_envelope_version() != 1:
        raise ValueError('ENVELOPE_NATIVE_UNAVAILABLE')
    return lib


def section(grid, profile, sign):
    from .muscle_section_profile import canonical_profile, checked_grid
    profile = canonical_profile(profile); grid = np.ascontiguousarray(checked_grid(grid))
    lib = library(); call = lib.af_muscle_envelope_profile
    call.argtypes = [POINTER(c_double), c_int, c_int, POINTER(c_double), c_int, c_int, POINTER(c_double)]
    call.restype = c_int
    params = np.array((*profile.depths, *profile.peaks, profile.roundness), dtype=float)
    output = np.empty_like(grid); mode = ('LOCAL', 'SMOOTH', 'SECTION').index(profile.direction)
    status = call(_double(grid), *grid.shape[:2], _double(params), mode, sign, _double(output))
    if status: raise ValueError('PROFILE_FRAME_DEGENERATE' if status == 2 else 'ENVELOPE_PROFILE_INVALID')
    return output


def legacy(grid, spec):
    from ctypes import byref
    from .muscle_numeric import make_muscle_request
    from .muscle_numeric_native import _input_row, _MuscleInput
    if spec.inflation_mode not in ('CTRL_POINT', 'DISTRIBUTED'): raise ValueError('PROFILE_MODE_UNSUPPORTED')
    grid = np.ascontiguousarray(grid, dtype=float); output = np.empty_like(grid)
    packed = _input_row(make_muscle_request('envelope', grid, spec), 0)
    call = library().af_muscle_envelope_legacy
    call.argtypes = [POINTER(c_double), POINTER(_MuscleInput), POINTER(c_double)]; call.restype = c_int
    if call(_double(grid), byref(packed), _double(output)): raise ValueError('ENVELOPE_LEGACY_FAILED')
    return output


def compose(first, second, faces, flip=False):
    first, second = (np.ascontiguousarray(v, dtype=float) for v in (first, second))
    faces = np.ascontiguousarray(faces, dtype=np.int64)
    if first.shape != second.shape or first.ndim != 2 or first.shape[1] != 3:
        raise ValueError('ENVELOPE_CORRESPONDENCE_INVALID')
    if not np.isfinite([first, second]).all(): raise ValueError('ENVELOPE_NONFINITE')
    lib = library(); call = lib.af_muscle_envelope_compose
    dp, ip = POINTER(c_double), POINTER(c_int64)
    call.argtypes = [dp, dp, c_int, ip, c_int, c_int, c_int, dp, ip, ip, ip, POINTER(c_int)]
    call.restype = c_int
    return _compose(call, first, second, faces, flip)


def _compose(call, a, b, faces, flip):
    vertices = np.empty((len(a)*2, 3)); output = np.empty((len(faces)*2, faces.shape[1]), dtype=np.int64)
    sources, sides = (np.empty(len(output), dtype=np.int64) for _ in range(2)); sizes = (c_int*2)()
    ptr = lambda array: array.ctypes.data_as(POINTER(c_int64))
    status = call(_double(a), _double(b), len(a), ptr(faces), len(faces), faces.shape[1], int(flip),
                  _double(vertices), ptr(output), ptr(sources), ptr(sides), sizes)
    if status: raise ValueError('ENVELOPE_COMPOSITION_FAILED')
    return vertices[:sizes[0]], output[:sizes[1]], sources[:sizes[1]], sides[:sizes[1]]


def diagnostics(vertices, faces):
    vertices = np.ascontiguousarray(vertices, dtype=float); faces = np.ascontiguousarray(faces, dtype=np.int64)
    call = library().af_muscle_envelope_diagnostics
    call.argtypes = [POINTER(c_double), c_int, POINTER(c_int64), c_int, c_int, POINTER(c_double)]
    call.restype = c_int; stats = np.zeros(4)
    status = call(_double(vertices), len(vertices), faces.ctypes.data_as(POINTER(c_int64)), len(faces), faces.shape[1], _double(stats))
    if status: raise ValueError('ENVELOPE_DIAGNOSTICS_FAILED')
    return dict(surface_area=float(stats[0]), boundary_edges=int(stats[1]), nonmanifold_edges=int(stats[2]),
                degenerate_faces=int(stats[3]), collision='not_checked', self_intersection='not_checked', volume_certified=False)


def side_diagnostics(base, side, faces, sign):
    base, side = (np.ascontiguousarray(v, dtype=float) for v in (base, side))
    faces = np.ascontiguousarray(faces, dtype=np.int64); stats = np.zeros(5)
    call = library().af_muscle_envelope_side_diagnostics
    call.argtypes = [POINTER(c_double), POINTER(c_double), c_int, POINTER(c_int64), c_int, c_int, c_int, POINTER(c_double)]
    call.restype = c_int
    status = call(_double(base), _double(side), len(base), faces.ctypes.data_as(POINTER(c_int64)), len(faces), faces.shape[1], sign, _double(stats))
    if status: raise ValueError('ENVELOPE_DIAGNOSTICS_FAILED')
    return dict(min_signed_depth=float(stats[0]), max_signed_depth=float(stats[1]), wrong_side_samples=int(stats[2]),
                large_normal_turns=int(stats[3]), degenerate_frames=int(stats[4]))
