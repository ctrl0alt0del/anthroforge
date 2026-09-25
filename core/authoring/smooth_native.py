"""Bounded C++ spline fitting. Python packs arrays; no optimizer fallback."""
from ctypes import POINTER, c_double, c_int, c_int64
import numpy as np
from ..vcp.v2.collision_native import load_native, _double
from .errors import require


def library():
    lib = load_native()
    require(hasattr(lib, 'af_base_spline_fit'), 'BASE_NATIVE_UNAVAILABLE', 'Rebuild the packaged native library.')
    d, i, p = POINTER(c_double), c_int, POINTER(c_int64)
    lib.af_base_spline_fit.argtypes = [d, i, d, i, p, i, i, i, i, p, c_double, c_double, d]
    lib.af_base_spline_fit.restype = i
    lib.af_base_spline_eval.argtypes = [d, i, i, d, i, i, d]; lib.af_base_spline_eval.restype = i
    return lib


def fit(grids, pins, seams, settings, fiber_counts=()):
    validate(grids, fiber_counts); shape = (max(fiber_counts) if fiber_counts else 4, settings.get('longitudinal_controls', 6))
    points = np.concatenate([g.reshape(-1, 3) for g in grids])
    origin = points.mean(axis=0); scale = float(np.linalg.norm(np.ptp(points, axis=0)))
    require(scale > 1e-9, 'BASE_DEGENERATE_INPUT')
    data = np.concatenate([sample_rows(g, i, origin, scale) for i, g in enumerate(grids)])
    constraints = np.asarray(pins, float).reshape(-1, 6).copy(); constraints[:, 3:] = (constraints[:, 3:]-origin)/scale
    joins = np.ascontiguousarray(seams, dtype=np.int64).reshape(-1, 4)
    out = np.empty((len(grids), *shape, 3), float)
    counts = np.ascontiguousarray(fiber_counts, dtype=np.int64)
    code = library().af_base_spline_fit(_double(data), len(data), _double(constraints), len(constraints),
        joins.ctypes.data_as(POINTER(c_int64)), len(joins), len(grids), *shape, counts.ctypes.data_as(POINTER(c_int64)) if fiber_counts else None,
        settings.get('fairness', .0001), settings.get('junction_smoothness', .001), _double(out))
    check(code); out = out*scale+origin
    return [c[:n].copy() for c, n in zip(out, fiber_counts)] if fiber_counts else out


def validate(grids, counts):
    require(1 <= len(grids) <= 8, 'BASE_INPUT_BUDGET')
    require(all(g.ndim == 3 and g.shape[2] == 3 and min(g.shape[:2]) >= 2 and np.isfinite(g).all() for g in grids), 'BASE_INVALID_GRID')
    require(sum(g.shape[0]*g.shape[1] for g in grids) <= 40000, 'BASE_INPUT_BUDGET')
    require(not counts or len(counts) == len(grids) and all(2 <= n <= 8 for n in counts), 'BASE_INVALID_FIBER_COUNTS')


def check(code):
    errors = {2: ('BASE_FIT_CONSTRAINTS', 'Pins or seam constraints conflict.'),
              4: ('BASE_ORDER_UNRESOLVED', 'Bounded ordering fit failed; revise head layout or attachment constraints.')}
    name, message = errors.get(code, ('BASE_NATIVE_FAILURE', str(code)))
    require(code == 0, name, message)


def sample_rows(grid, index, origin, scale):
    uv = coordinates(*grid.shape[:2]); weights = np.full(len(uv), 1/len(uv))
    weights[np.any((uv == 0) | (uv == 1), axis=1)] *= 5
    return np.ascontiguousarray(np.c_[np.full(len(uv), index), uv, (grid.reshape(-1, 3)-origin)/scale, weights])


def coordinates(across, along):
    return np.asarray([(u, v) for u in np.linspace(0, 1, across) for v in np.linspace(0, 1, along)])


def evaluate(controls, uv, linear=False):
    controls = np.ascontiguousarray(controls, dtype=float); uv = np.ascontiguousarray(uv, dtype=float)
    out = np.empty((len(uv), 3)); require(controls.ndim == 3 and controls.shape[2] == 3, 'BASE_INVALID_CONTROLS')
    require(uv.ndim == 2 and uv.shape[1] == 2, 'BASE_INVALID_COORDINATES')
    code = library().af_base_spline_eval(_double(controls), *controls.shape[:2], _double(uv), len(uv), int(linear), _double(out))
    require(code == 0, 'BASE_NATIVE_EVALUATION'); return out


def faces(across, along):
    return np.asarray([(a, a+along, a+along+1) for u in range(across-1) for v in range(along-1) for a in [u*along+v]] +
                      [(a, a+along+1, a+1) for u in range(across-1) for v in range(along-1) for a in [u*along+v]], int)
