"""Native local partition with locked endpoints and bounded outline error."""
from ctypes import POINTER, c_double, c_int, c_int64
import numpy as np
from .errors import require
from ..vcp.v2.collision_native import load_native, _double


def library():
    lib = load_native(); require(hasattr(lib, 'af_base_partition'), 'PARTITION_NATIVE_UNAVAILABLE')
    d, i, p = POINTER(c_double), c_int, POINTER(c_int64)
    lib.af_base_partition.argtypes = [d, i, i, d, i, i, p, d, d, d, d, POINTER(i), d]
    lib.af_base_partition.restype = i
    return lib


def frame(settings):
    x, y = np.asarray(settings['along_axis'], float), np.asarray(settings['across_axis'], float)
    require(x.shape == y.shape == (3,) and np.isfinite([x, y]).all(), 'PARTITION_INVALID_FRAME')
    require(np.linalg.norm(x) > 1e-12, 'PARTITION_INVALID_FRAME'); x = x/np.linalg.norm(x)
    y = y-x*np.dot(x, y); require(np.linalg.norm(y) > 1e-12, 'PARTITION_INVALID_FRAME')
    y = y/np.linalg.norm(y); return np.ascontiguousarray([x, y, np.cross(x, y)])


def inputs(paths, sides, settings):
    try: grids = [np.ascontiguousarray(p, dtype=float) for p in paths]
    except (TypeError, ValueError): require(False, 'PARTITION_INVALID_STRIPS')
    require(len(grids) == 2 and all(p.ndim == 3 and p.shape[2] == 3 and 2 <= len(p) <= 8 and 2 <= p.shape[1] <= 1025 and np.isfinite(p).all() for p in grids), 'PARTITION_INVALID_STRIPS')
    require(sum(p.size//3 for p in grids) <= 8192, 'PARTITION_INPUT_BUDGET')
    require(len(sides) == 2 and all(s in (0, 1) for s in sides), 'PARTITION_INVALID_SIDES')
    values = np.ascontiguousarray([settings[k] for k in ('blend_distance', 'max_displacement', 'max_depth_gap')], float)
    require(np.isfinite(values).all() and np.all(values[:2] > 0) and values[2] >= 0, 'PARTITION_INVALID_LIMITS')
    return grids, np.ascontiguousarray(sides, dtype=np.int64), frame(settings), values


def check(code):
    names = {1: 'INVALID_INPUT', 2: 'NONMONOTONE_CHART', 3: 'SIDE_ORDER', 4: 'DEPTH_GAP',
             5: 'DISPLACEMENT_LIMIT', 6: 'LOCKED_ENDPOINT', 7: 'NO_COMMON_SPAN', 8: 'NATIVE_FAILURE'}
    require(code == 0, 'PARTITION_'+names.get(code, 'NATIVE_FAILURE'))


def calculate(paths, sides, settings):
    grids, side, axes, values = inputs(paths, sides, settings); a, b = grids
    sizes = np.zeros(2, np.int32); stats = np.zeros(3)
    args = [_double(a), *a.shape[:2], _double(b), *b.shape[:2], side.ctypes.data_as(POINTER(c_int64)), _double(axes), _double(values)]
    tail = [sizes.ctypes.data_as(POINTER(c_int)), _double(stats)]; method = library().af_base_partition
    check(method(*args, None, None, *tail))
    require(max(sizes) <= 16384 and sum(len(g)*n for g, n in zip(grids, sizes)) <= 65536, 'PARTITION_OUTPUT_BUDGET')
    output = [np.empty((len(g), n, 3)) for g, n in zip(grids, sizes)]
    check(method(*args, *map(_double, output), *tail))
    return finish(grids, output, axes, stats, settings)


def finish(grids, output, axes, stats, settings):
    if stats[0] <= 1e-9: output = [g.copy() for g in grids]; stats[2] = 0.
    require(stats[2] <= settings.get('max_outline_error', 1e-5), 'PARTITION_OUTLINE_CHANGE', str(stats[2]))
    for old, new in zip(grids, output): new[:, [0, -1]] = old[:, [0, -1]]
    return dict(paths=[p.tolist() for p in output], stations=[stations(p, axes[0]) for p in output],
        maximum_displacement=float(stats[0]), outer_border_resampling_error=float(stats[2]), common_border_length_along_axis=float(stats[1]),
        changed=bool(stats[0] > 1e-9), method='local shared border; depth blend; locked endpoints; bounded outline resampling')


def stations(paths, axis):
    xs = paths @ axis; low, high = float(xs.min()), float(xs.max())
    values = (xs-low)/(high-low)
    if values[0, 0] > values[0, -1]: values = 1-values
    values[:, 0] = 0; values[:, -1] = 1; values[:] = values[0]
    require(np.all(np.diff(values, axis=1) > 0), 'PARTITION_STATION_ORDER')
    return values.tolist()


def native_mesh(paths, stations):
    from ..vcp.fiber_surface import evaluate_fiber_surface, FiberSurfaceSpec
    result = evaluate_fiber_surface(paths, FiberSurfaceSpec(exact_samples=True, parameter_stations=tuple(stations)))
    quads = np.asarray(result.faces); triangles = np.concatenate((quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]))
    return dict(vertices=list(result.vertices), triangles=triangles.tolist(), rows=len(result.rows), columns=len(result.rows[0]))
