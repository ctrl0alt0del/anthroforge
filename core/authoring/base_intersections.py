"""Batched native intersection diagnostics for immutable published base snapshots."""
import ctypes as C
from functools import lru_cache
import numpy as np
from ..vcp.v2.collision_native import load_native

DP, IP = C.POINTER(C.c_double), C.POINTER(C.c_int64)
KINDS = ('crossing', 'coplanar_overlap', 'contact')


class Input(C.Structure):
    _fields_ = [('vertices', DP), ('faces', IP), ('vertex_count', C.c_int), ('face_count', C.c_int)]


class Pair(C.Structure):
    _fields_ = [(k, C.c_int64) for k in ('first', 'second')]+[('counts', C.c_int64*3)]
    _fields_ += [(k, C.c_int64) for k in ('start', 'size')]+[('area', C.c_double)]


class Witness(C.Structure):
    _fields_ = [(k, C.c_int64) for k in ('first_face', 'second_face', 'kind')]
    _fields_ += [(k, C.c_double*3) for k in ('first', 'second')]


@lru_cache(maxsize=1)
def library():
    try:
        lib = load_native()
        calls = dict(version=([], C.c_int), free=([C.c_void_p], None), sizes=([C.c_void_p, IP], C.c_int),
            scan=([C.POINTER(Input), C.c_int, C.c_double, C.c_int, C.c_char_p, C.c_int], C.c_void_p),
            copy=([C.c_void_p, C.POINTER(Pair), C.POINTER(Witness), IP], C.c_int))
        for name, (args, result) in calls.items():
            fn = getattr(lib, 'af_base_intersections_'+name); fn.argtypes, fn.restype = args, result
        if lib.af_base_intersections_version() != 1: raise RuntimeError('BASE_NATIVE_VERSION')
        return lib
    except (OSError, AttributeError, RuntimeError) as error:
        raise RuntimeError('BASE_INTERSECTIONS_NATIVE_UNAVAILABLE: '+str(error)) from error


def arrays(mesh):
    vertices = np.ascontiguousarray(mesh['vertices'], dtype=np.float64)
    faces = np.ascontiguousarray(mesh['triangles'], dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all(): raise ValueError('BASE_COORDINATES')
    if faces.ndim != 2 or faces.shape[1] != 3 or not len(faces): raise ValueError('BASE_EMPTY_MESH')
    if not np.array_equal(faces, mesh['triangles']) or faces.min() < 0 or faces.max() >= len(vertices): raise ValueError('BASE_FACE_INDEX')
    return vertices, faces


def scan(meshes, tolerance=1e-7, witness_limit=8):
    if not np.isfinite(tolerance) or tolerance <= 0: raise ValueError('BASE_TOLERANCE')
    if type(witness_limit) is not int or not 0 <= witness_limit <= 64: raise ValueError('BASE_WITNESS_LIMIT')
    values = [arrays(mesh) for mesh in meshes]
    inputs = (Input*len(values))(*(Input(v.ctypes.data_as(DP), f.ctypes.data_as(IP), len(v), len(f)) for v, f in values))
    lib = library(); error = C.create_string_buffer(512)
    handle = lib.af_base_intersections_scan(inputs, len(values), tolerance, witness_limit, error, len(error))
    if not handle: raise RuntimeError(error.value.decode() or 'BASE_SCAN_FAILED')
    try: return read_result(lib, handle, meshes, witness_limit)
    finally: lib.af_base_intersections_free(handle)


def read_result(lib, handle, meshes, limit):
    sizes = (C.c_int64*5)()
    if lib.af_base_intersections_sizes(handle, sizes): raise RuntimeError('BASE_SCAN_READ_FAILED')
    pairs, witnesses, degenerate = (Pair*sizes[0])(), (Witness*sizes[1])(), (C.c_int64*sizes[2])()
    if lib.af_base_intersections_copy(handle, pairs, witnesses, degenerate): raise RuntimeError('BASE_SCAN_READ_FAILED')
    rows = [pair_record(p, witnesses, meshes, limit) for p in pairs]
    issues = [dict(code='BASE_DEGENERATE_TRIANGLES', surface=m['identity'], count=n) for m, n in zip(meshes, degenerate) if n]
    return dict(pairs=rows, issues=issues, broad_phase_pairs=sizes[3], triangle_tests=sizes[4],
                tested_surface_pairs=len(meshes)*(len(meshes)-1)//2)


def pair_record(pair, witnesses, meshes, limit):
    first, second = meshes[pair.first], meshes[pair.second]
    counts = dict(zip(KINDS, pair.counts))
    return dict(first=first['identity'], second=second['identity'], triangle_pair_counts=counts,
        intersection=bool(counts['crossing'] or counts['coplanar_overlap']), coplanar_area=pair.area,
        witnesses_truncated=any(count>limit for count in pair.counts),
        witnesses=[witness_record(w, first, second) for w in witnesses[pair.start:pair.start+pair.size]])


def witness_record(witness, first, second):
    a, b = witness.first_face, witness.second_face
    return dict(kind=KINDS[witness.kind-1], first_triangle=a, second_triangle=b,
        first_polygon=int(first.get('polygons', range(len(first['triangles'])))[a]),
        second_polygon=int(second.get('polygons', range(len(second['triangles'])))[b]),
        first_vertices=np.asarray(first['triangles'][a]).tolist(), second_vertices=np.asarray(second['triangles'][b]).tolist(),
        segment=[list(witness.first), list(witness.second)])
