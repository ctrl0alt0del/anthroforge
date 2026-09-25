"""Native material-boundary correspondence and transition-envelope guides."""
import ctypes as ct
import numpy as np
from ..vcp.v2.collision_native import load_native
from .errors import require
from .attachment_graft_mesh import sample_loop, fractions


def normals(v, f):
    n = np.zeros_like(v); cross = np.cross(v[f[:, 1]]-v[f[:, 0]], v[f[:, 2]]-v[f[:, 0]])
    for i in range(3):
        np.add.at(n, f[:, i], cross)
    return n/np.maximum(np.linalg.norm(n, axis=1)[:, None], 1e-30)


def departure(v, f, loop, count, direction):
    n = -normals(v, f)[loop]; t = np.r_[fractions(v, loop), 1.]; n = np.vstack([n, n[0]])
    values = np.column_stack([np.interp(np.arange(count)/count, t, n[:, i]) for i in range(3)])
    values = .25*values+np.asarray(direction)
    require(np.linalg.norm(values, axis=1).min() > 1e-10, 'ATTACHMENT_DEPARTURE_INVALID')
    return values/np.linalg.norm(values, axis=1)[:, None]


def calculate(first, second, directions, frames, escape):
    lib = load_native(); dp = ct.POINTER(ct.c_double); ip = ct.POINTER(ct.c_int)
    require(hasattr(lib, 'af_attachment_graft'), 'ATTACHMENT_NATIVE_UNAVAILABLE', 'Rebuild native library and restart Blender.')
    lib.af_attachment_graft.argtypes = [ct.c_int, ct.c_int, dp, dp, dp, dp, ct.c_double, dp, ip]
    arrays = [np.ascontiguousarray(p, float) for p in (first, second, directions, frames)]
    require(3 <= len(first) <= 1024 and all(p.shape == (len(first), 3) for p in arrays[:3]) and arrays[3].shape == (4, 3), 'ATTACHMENT_NATIVE_SHAPE')
    require(all(np.isfinite(p).all() for p in arrays) and np.isfinite(escape) and escape >= 0, 'ATTACHMENT_NATIVE_VALUES')
    result = np.zeros((24, len(first), 3)); order = np.zeros(2, np.int32)
    code = lib.af_attachment_graft(len(first), 24, *[p.ctypes.data_as(dp) for p in arrays], escape, result.ctypes.data_as(dp), order.ctypes.data_as(ip))
    require(code == 0 and np.isfinite(result).all(), 'ATTACHMENT_NATIVE_FAILED', str(code))
    return result.reshape(-1, 3), order.tolist()


def guides(patch, retained, settings):
    pv, pf, pl = patch; cv, _cf, cl = retained; count = 96
    first, second = sample_loop(pv, pl, count), sample_loop(cv, cl, count)
    direction = np.asarray(settings['departure_direction'], float); direction /= np.linalg.norm(direction)
    directions = departure(pv, pf, pl, count, direction)
    frames = [*settings['attachment_axes'], *settings['retained_axes']]
    return calculate(first, second, directions, frames, settings['escape_distance'])
