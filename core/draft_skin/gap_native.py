"""Batched native gap queries; no numerical Python fallback."""
import ctypes as ct
import numpy as np
from .gap_settings import effective_gap

_LIBRARY = None


def library():
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = _load_library()
    return _LIBRARY


def _load_library():
    from ..vcp.v2.collision_native import load_native, native_path
    try:
        loaded = load_native(native_path())
        if loaded.af_skin_gap_version() != 3 or loaded.af_skin_tiles_memory_version() != 1:
            raise ValueError('incompatible gap capability')
        if loaded.af_skin_gap_validation_version() != 2:
            raise ValueError('incompatible gap validation capability')
        _configure(loaded)
        return loaded
    except (OSError, AttributeError, ValueError) as error:
        raise RuntimeError('Draft skin requires native gap v3, compact field v1 and contact validation v2; install the matching bundle. '
                           'Previous output retained.') from error


def _configure(lib):
    double = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
    integer = np.ctypeslib.ndpointer(dtype=np.int64, flags="C_CONTIGUOUS")
    owners = np.ctypeslib.ndpointer(dtype=np.int32, flags="C_CONTIGUOUS")
    lib.af_skin_gap_create.argtypes = [double, ct.c_int, integer, ct.c_int, owners, ct.c_int, double]
    lib.af_skin_gap_create.restype = ct.c_void_p
    lib.af_skin_gap_destroy.argtypes = [ct.c_void_p]
    lib.af_skin_gap_destroy.restype = None
    lib.af_skin_gap_sample.argtypes = [ct.c_void_p, double, ct.c_int, ct.c_double, double]
    lib.af_skin_gap_sample.restype = ct.c_int




class GapQueries:
    def __init__(self, capture):
        self.lib = library()
        self.source_indices = np.asarray([s.source_index for s in capture.sources], dtype=np.int32)
        vertices, faces, owners, policies = _arrays(capture)
        self.handle = self.lib.af_skin_gap_create(vertices, len(vertices), faces, len(faces), owners, len(policies), policies)
        if not self.handle:
            raise ValueError("Cannot build draft-skin gap queries: invalid geometry or native allocation failure.")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        if self.handle:
            self.lib.af_skin_gap_destroy(self.handle)
        self.handle = None

    def sample(self, points, reach):
        points = point_array(points)
        output = np.empty((len(points), 13), dtype=np.float64)
        if not self.handle or self.lib.af_skin_gap_sample(self.handle, points, len(points), reach, output):
            raise RuntimeError("Native draft-skin gap query failed.")
        return output



def _arrays(capture):
    sources = capture.sources
    for source in sources:
        face_array(source.triangles, len(point_array(source.vertices)))
    offsets = np.r_[0, np.cumsum([len(s.vertices) for s in sources])]
    vertices = np.ascontiguousarray(np.concatenate([s.vertices for s in sources]), dtype=np.float64)
    faces = np.ascontiguousarray(np.concatenate([s.triangles + offsets[i] for i, s in enumerate(sources)]), dtype=np.int64)
    owners = np.repeat(np.arange(len(sources), dtype=np.int32), [len(s.triangles) for s in sources])
    policies = np.asarray([(*effective_gap(s, capture.settings), s.entity_type == "SCP") for s in sources], dtype=np.float64)
    policies[:, 0] *= float(np.max(capture.upper - capture.lower))
    return vertices, faces, owners, policies


def point_array(points):
    values = np.ascontiguousarray(points, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3 or not np.isfinite(values).all():
        raise ValueError("Draft-skin geometry must be a finite N by 3 array.")
    return values


def face_array(faces, count):
    values = np.asarray(faces)
    if values.ndim != 2 or values.shape[1] != 3 or not np.issubdtype(values.dtype, np.integer):
        raise ValueError("Draft-skin triangles must be an integer N by 3 array.")
    if values.size and (values.min() < 0 or values.max() >= count):
        raise ValueError("Draft-skin triangle index is outside its source geometry.")
    return np.ascontiguousarray(values, dtype=np.int64)
