"""Separately versioned ordering and stacking interfaces, in the fiber library."""
import ctypes as C
from functools import lru_cache
from ..muscle_pairs import abi as pairs


class Settings(C.Structure):
    _fields_ = [('enabled', C.c_int)] + [(k, C.c_double) for k in ('clearance', 'radius', 'strength', 'maximum')]


class Material(C.Structure):
    _fields_ = [('id', C.c_uint64), ('material', pairs.DP), ('faces', pairs.IP), ('interpolation', pairs.IP)]
    _fields_ += [('weights', pairs.DP), ('fixed', pairs.IP)]
    _fields_ += [(k, C.c_int) for k in ('vertices', 'triangles', 'samples', 'width', 'pins', 'valid')]


class Order(C.Structure):
    _fields_ = [(k, C.c_uint64) for k in ('first', 'second', 'underlying', 'covering')]
    _fields_ += [(k, C.c_int) for k in ('status', 'warnings')]
    _fields_ += [('positive', C.c_double*2), ('negative', C.c_double*2)]
    _fields_ += [(k, C.c_double) for k in ('coincident', 'minimum', 'maximum')]
    _fields_ += [(k, C.c_int64) for k in ('fragments', 'points', 'crossings')]
    _fields_ += [('diagnostic', C.c_char*128)]


class Output(C.Structure):
    _fields_ = [('id', C.c_uint64), ('status', C.c_int), ('vertices', C.c_int64)]
    _fields_ += [(k, C.c_double) for k in ('maximum', 'map_ms', 'solve_ms', 'validation_ms')]
    _fields_ += [(k, C.c_int64) for k in ('baseline_self', 'baseline_bone_crossings', 'open_obstacles')]
    _fields_ += [('baseline_penetration', C.c_double), ('message', C.c_char*256)]


class Obstacle(C.Structure):
    _fields_ = [('vertices', pairs.DP), ('faces', pairs.IP), ('count', C.c_int), ('triangles', C.c_int)]


@lru_cache(maxsize=1)
def library():
    try:
        lib = pairs.library(); H, U, I, P = C.c_void_p, C.c_uint64, C.c_int, C.POINTER
        calls = dict(af_stack_submit=[H, P(pairs.Input), I, P(pairs.Settings), P(Material), P(Settings), P(U), I, P(Obstacle), I, U],
            af_layer_summary=[H, U, P(Order), I, pairs.DP], af_layer_resolve_pair=[H, U, U, U, I, P(Order)], af_stack_summary=[H, U, P(Output), I],
            af_stack_output=[H, U, U, pairs.DP, I], af_layer_footprint=[H, U, I, P(pairs.Fragment), I, P(pairs.Point), I],
            af_layer_storage_stats=[H, U, pairs.DP, I])
        for name, args in calls.items(): getattr(lib, name).argtypes, getattr(lib, name).restype = args, I
        if lib.af_layer_order_version() != 1 or lib.af_stacking_version() != 1: raise RuntimeError('STACK_NATIVE_VERSION')
        return lib
    except (AttributeError, RuntimeError, OSError) as error: raise RuntimeError('STACK_NATIVE_UNAVAILABLE: '+str(error)) from error
