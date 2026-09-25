"""Batched native shape transfer; no Python fitting or optimization fallback."""
import ctypes as ct
from time import perf_counter
import numpy as np
from ..vcp.v2.collision_native import load_native, NativeCollisionWorld
from .errors import require

DP, IP = ct.POINTER(ct.c_double), ct.POINTER(ct.c_int)
DEFAULTS = dict(radius_fraction=.30, cluster_radius_fraction=.20, bridge_fraction=.015,
                shape_strength=18., collision_strength=60., clearance=.002,
                convergence=1e-5, far_influence=.08, max_iterations=240)


class Input(ct.Structure):
    _fields_ = [(k, ct.c_int) for k in ('abi', 'n', 'nf', 'nw', 'reflection', 'iterations')]
    _fields_ += [(k, DP) for k in ('source', 'target')]+[(k, IP) for k in ('fixed', 'faces')]
    _fields_ += [('worlds', ct.POINTER(ct.c_void_p))]
    _fields_ += [(k, ct.c_double) for k in ('radius', 'cluster_radius', 'bridge', 'shape', 'collision', 'clearance', 'convergence', 'far_influence')]
    _fields_ += [(k, DP) for k in ('rest', 'influence', 'output', 'stats')]


def library():
    lib = load_native()
    require(hasattr(lib, 'af_transfer_shape_fit'), 'TRANSFER_SHAPE_NATIVE_UNAVAILABLE', 'Rebuild the packaged native library; restart Blender.')
    lib.af_transfer_shape_fit.argtypes = [ct.POINTER(Input)]; lib.af_transfer_shape_fit.restype = ct.c_int
    return lib


def world(bone):
    value, closed = NativeCollisionWorld.from_batch([bone.vertices], [bone.faces], [0])
    if not all(closed):
        value.close(); require(False, 'TRANSFER_SHAPE_OPEN_OBSTACLE', bone.identity)
    return value


def validate(source, target, faces, fixed, settings, reflection):
    require(source.ndim == 2 and source.shape[1] == 3 and target.shape == source.shape, 'TRANSFER_SHAPE_ARRAYS')
    require(4 <= len(source) <= 100000 and faces.ndim == 2 and faces.shape[1] == 3 and 1 <= len(faces) <= 200000, 'TRANSFER_SHAPE_BUDGET')
    require(np.isfinite(source).all() and np.isfinite(target).all(), 'TRANSFER_SHAPE_NONFINITE')
    require(np.ptp(source, axis=0).max() > 1e-12 and np.ptp(target, axis=0).max() > 1e-12, 'TRANSFER_SHAPE_DEGENERATE')
    require(np.isfinite(faces).all() and np.equal(faces, np.floor(faces)).all() and faces.min() >= 0 and faces.max() < len(source), 'TRANSFER_SHAPE_INDEX')
    require(fixed.shape == (len(source),) and np.isin(fixed, [0, 1]).all() and fixed.any(), 'TRANSFER_SHAPE_BANDS')
    require(all(np.isfinite(v) and v >= 0 for v in settings.values()), 'TRANSFER_SHAPE_SETTINGS')
    require(0 < settings['radius_fraction'] <= 2 and 0 < settings['cluster_radius_fraction'] <= 1 and settings['bridge_fraction'] <= .1, 'TRANSFER_SHAPE_SETTINGS')
    require(0 < settings['shape_strength'] <= 1000 and settings['collision_strength'] <= 1000 and settings['far_influence'] <= 1, 'TRANSFER_SHAPE_SETTINGS')
    require(1 <= settings['max_iterations'] <= 1000 and int(settings['max_iterations']) == settings['max_iterations'] and settings['convergence'] > 0, 'TRANSFER_SHAPE_SETTINGS')
    require(reflection in (-1, 1), 'TRANSFER_SHAPE_ORIENTATION')


def fit(source, target, faces, fixed, bones, settings=None, reflection=1):
    settings = dict(DEFAULTS, **(settings or {})); require(set(settings) == set(DEFAULTS), 'TRANSFER_SHAPE_SETTINGS')
    source, target, faces, fixed = [np.asarray(a) for a in (source, target, faces, fixed)]
    validate(source, target, faces, fixed, settings, reflection); lib = library(); worlds = []
    require(len(bones) <= 32 and (bones or settings['collision_strength'] == 0), 'TRANSFER_SHAPE_OBSTACLES')
    try:
        for bone in bones:
            worlds.append(world(bone))
        return calculate(lib, source, target, faces, fixed, worlds, settings, reflection)
    finally:
        for value in worlds:
            value.close()


def calculate(lib, source, target, faces, fixed, worlds, settings, reflection):
    arrays = [np.ascontiguousarray(a, dtype=t) for a, t in ((source, float), (target, float), (fixed, np.int32), (faces, np.int32))]
    outputs = [np.zeros_like(arrays[0]), np.zeros(len(source)), np.zeros_like(arrays[0]), np.zeros(13)]
    handles = (ct.c_void_p*len(worlds))(*[w.handle for w in worlds])
    values = [settings[k] for k in ('radius_fraction', 'cluster_radius_fraction', 'bridge_fraction', 'shape_strength', 'collision_strength', 'clearance', 'convergence', 'far_influence')]
    args = Input(1, len(source), len(faces), len(worlds), reflection, int(settings['max_iterations']),
                 *[a.ctypes.data_as(DP if i < 2 else IP) for i, a in enumerate(arrays)], handles,
                 *values, *[a.ctypes.data_as(DP) for a in outputs])
    started = perf_counter(); code = lib.af_transfer_shape_fit(ct.byref(args))
    require(code == 0, 'TRANSFER_SHAPE_NATIVE_FAILED', {1: 'Invalid or degenerate input.', 2: 'Allocation budget.', 3: 'Native calculation or query failed.'}.get(code, str(code)))
    require(all(np.isfinite(a).all() for a in outputs), 'TRANSFER_SHAPE_NONFINITE_OUTPUT')
    return dict(vertices=outputs[2], rest=outputs[0], influence=outputs[1], fitting=statistics(outputs[3], settings, perf_counter()-started))


def statistics(stats, settings, seconds):
    return dict(method='cluster_shape_matching.v1', iterations=int(stats[2]), last_rms_step=float(stats[1]),
                stop_reason='step_tolerance' if stats[1] < settings['convergence'] else 'iteration_limit',
                similarity_scale=float(stats[0]), seconds=seconds, settings=settings,
                curvature_preservation='approximate', volume_preservation='not_constrained', clearance_certificate=False)
