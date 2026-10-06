"""Versioned pair-detection ABI in the existing packaged native library."""
import ctypes as C
from functools import lru_cache
from ..vcp.v2.collision_native import load_native

DP, IP = C.POINTER(C.c_double), C.POINTER(C.c_int64)


class Settings(C.Structure):
    _fields_ = [(k, C.c_double) for k in ('search', 'area', 'epsilon')]
    _fields_ += [(k, C.c_int) for k in ('limit', 'workers')]
    _fields_ += [(k, C.c_uint64) for k in ('cache_bytes', 'result_bytes')]


class Input(C.Structure):
    _fields_ = [('id', C.c_uint64)] + [(k, DP) for k in ('base', 'own', 'direction')]
    _fields_ += [(k, IP) for k in ('faces', 'parts', 'sources')]
    _fields_ += [(k, C.c_int) for k in ('vertices', 'triangles', 'family', 'root', 'instance', 'enabled', 'side')]
    _fields_ += [('displacement', C.c_double)]


class Report(C.Structure):
    _fields_ = [('state', C.c_int), ('generation', C.c_uint64), ('stats', C.c_double * 16), ('message', C.c_char * 512)]


class Pair(C.Structure):
    _fields_ = [(k, C.c_int64) for k in ('first', 'second', 'start', 'count', 'warnings', 'points')]


class Fragment(C.Structure):
    _fields_ = [(k, C.c_int64) for k in ('receiver', 'provider', 'receiver_face', 'provider_face', 'start', 'count')]
    _fields_ += [(k, C.c_double) for k in ('area', 'gap_min', 'gap_max', 'alignment')]


class Point(C.Structure):
    _fields_ = [(k, C.c_double * 3) for k in ('receiver', 'provider', 'world_receiver', 'world_provider')]


def configure(lib):
    H, U, I = C.c_void_p, C.c_uint64, C.c_int
    calls = dict(create=([], H), destroy=([H], None), version=([], I),
        submit=([H, C.POINTER(Input), I, C.POINTER(Settings), U, I], I),
        poll=([H, C.POINTER(Report)], I), summary=([H, U, C.POINTER(Pair), I], I),
        footprint=([H, U, I, C.POINTER(Fragment), I, C.POINTER(Point), I], I))
    calls.update({name: ([H, U], I) for name in ('cancel', 'release')})
    calls.update(storage_version=([], I), storage_stats=([H, U, DP, I], I))
    for name, (args, result) in calls.items():
        fn = getattr(lib, 'af_pair_' + name); fn.argtypes, fn.restype = args, result
    if lib.af_pair_version() != 1 or lib.af_pair_storage_version() != 1: raise RuntimeError('PAIR_NATIVE_VERSION')
    for name in ('limiting', 'build_field', 'blend_directions', 'orientation'): getattr(lib, 'af_pair_' + name)
    return lib


@lru_cache(maxsize=1)
def library():
    try: return configure(load_native())
    except (OSError, AttributeError, RuntimeError) as error:
        raise RuntimeError('PAIR_NATIVE_UNAVAILABLE: ' + str(error)) from error


def pointer(value):
    return value.ctypes.data_as(DP if value.dtype.kind == 'f' else IP)
