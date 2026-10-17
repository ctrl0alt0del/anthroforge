"""Batched native height denoising; no numerical iteration in Python."""
from ctypes import CDLL, Structure, POINTER, byref, c_double, c_int, c_int64, c_char
from functools import lru_cache
from pathlib import Path
from ..native_platform import library_path
import numpy as np


class Report(Structure):
    _fields_ = [(key, c_int) for key in ('status', 'iterations', 'samples', 'pinned', 'skipped_triangles')]
    _fields_ += [(key, c_double) for key in ('total_ms', 'solve_ms', 'violation', 'stationarity', 'complementarity', 'max_change', 'complementarity_relative', 'objective')]
    _fields_ += [('message', c_char*512)]


@lru_cache(maxsize=1)
def library():
    path = library_path('native/smoothing/af_height_smoothing_v1.dll')
    try: lib = CDLL(str(path))
    except OSError as error: raise RuntimeError('SMOOTHING_NATIVE_UNAVAILABLE: '+str(error)) from error
    lib.af_height_version.restype = c_int
    if lib.af_height_version() != 1: raise RuntimeError('SMOOTHING_NATIVE_VERSION')
    dp, ip = POINTER(c_double), POINTER(c_int64)
    lib.af_height_smooth.argtypes = [dp, dp, c_int, ip, c_int, c_int, ip, c_int, c_double, c_double, c_double, dp, POINTER(Report)]
    lib.af_height_smooth.restype = c_int
    return lib


def smooth(base, own, faces, labels, part, settings):
    base, own = (np.ascontiguousarray(v, dtype=np.float64) for v in (base, own))
    faces, labels = (np.ascontiguousarray(v, dtype=np.int64) for v in (faces, labels))
    _validate(base, own, faces, labels)
    output = np.empty_like(own); report = Report()
    dp = lambda v: v.ctypes.data_as(POINTER(c_double))
    ip = lambda v: v.ctypes.data_as(POINTER(c_int64))
    code = library().af_height_smooth(dp(base), dp(own), len(base), ip(faces), len(faces), faces.shape[1],
        ip(labels), part, settings.radius, settings.strength, settings.max_change, dp(output), byref(report))
    if code: _failed(report)
    return output, {key: getattr(report, key) for key, _ in Report._fields_ if key != 'message'}


def _failed(report):
    message = report.message.decode('utf8', errors='replace')
    raise ValueError(f'SMOOTHING_FAILED: {message}; residuals '
        f'primal={report.violation:.3g}, stationary={report.stationarity:.3g}, complementary={report.complementarity:.3g}')


def _validate(base, own, faces, labels):
    if base.ndim != 2 or base.shape[1] != 3 or own.shape != base.shape or len(base) < 3:
        raise ValueError('SMOOTHING_COORDINATES_INVALID')
    if faces.ndim != 2 or faces.shape[1] not in (3, 4) or labels.shape != (len(faces),):
        raise ValueError('SMOOTHING_TOPOLOGY_INVALID')
    if len(faces) == 0 or len(base) > 2147483647 or len(faces) > 2147483647:
        raise ValueError('SMOOTHING_SIZE_INVALID')
