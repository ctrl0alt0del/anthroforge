"""Batched native field construction and path routing."""
import ctypes as C
from pathlib import Path
import numpy as np

P = np.ctypeslib.ndpointer(np.float64, flags="C_CONTIGUOUS")
I = np.ctypeslib.ndpointer(np.int32, flags="C_CONTIGUOUS")


def library():
    path = Path(__file__).resolve().parents[2] / "native/topology/af_topology_field_v1.dll"
    lib = C.CDLL(str(path))
    if lib.af_topology_version() != 1: raise RuntimeError("Incompatible native topology field library.")
    lib.af_field.argtypes = [P, I, C.c_int, P, P, P, P, I, C.c_int, C.c_double, C.c_int, P, P]
    lib.af_path.argtypes = [P, C.c_int, I, C.c_int, P, C.c_int, I, C.c_int]
    lib.af_select_paths.argtypes = [P, I, C.c_int, C.c_double, I]
    return lib


def arrays(vertices, faces):
    v, f = np.ascontiguousarray(vertices, np.float64), np.ascontiguousarray(faces, np.int32)
    if v.ndim != 2 or v.shape[1] != 3 or not len(v) or not np.isfinite(v).all(): raise ValueError("Invalid field vertices.")
    if f.ndim != 2 or f.shape[1] != 3 or not len(f) or f.min() < 0 or f.max() >= len(v): raise ValueError("Invalid field triangles.")
    return v, f


def solve(vertices, faces, prior, samples):
    v, f = arrays(vertices, faces); s = np.asarray(samples, np.float64)
    if s.ndim != 2 or s.shape[1] != 10 or not np.isfinite(s).all(): raise ValueError("Invalid FLOW samples.")
    prior = np.ascontiguousarray(prior, np.float64)
    if prior.shape != (len(f), 3) or not np.isfinite(prior).all(): raise ValueError("Invalid prior cross field.")
    out = np.empty((len(f), 3)); info = np.empty_like(out)
    values = [np.ascontiguousarray(s[:, i:i+3]) for i in (0, 3, 6)]
    radius = max(float(np.ptp(v, axis=0).max()) * .035, 1e-10)
    ok = library().af_field(v, f, len(f), prior, *values, np.ascontiguousarray(s[:, 9], np.int32), len(s), radius, 1, out, info)
    if not ok or not np.isfinite(out).all(): raise RuntimeError("Native FLOW field failed.")
    return out, info


def route(vertices, faces, points):
    v, f = arrays(vertices, faces); p = np.ascontiguousarray(points, np.float64)
    if p.ndim != 2 or p.shape[1] != 3 or len(p) < 2 or not np.isfinite(p).all(): raise ValueError("Invalid feature path.")
    out = np.empty(len(f) * 6, np.int32)
    count = library().af_path(v, len(v), f, len(f), p, len(p), out, len(out))
    if count < 0: raise ValueError("Feature path could not be routed within the mesh and work budget.")
    return out[:count*2].reshape(-1, 2)


def select_paths(vertices, paths):
    if not paths: return []
    points = np.ascontiguousarray(np.vstack(paths), np.float64)
    offsets = np.ascontiguousarray(np.r_[0, np.cumsum([len(p) for p in paths])], np.int32)
    if not np.isfinite(points).all(): raise ValueError("Nonfinite feature paths.")
    selected = np.empty(len(paths), np.int32); radius = float(np.ptp(vertices, axis=0).max()) * .08
    count = library().af_select_paths(points, offsets, len(paths), radius, selected)
    if count < 0: raise RuntimeError("Native feature path selection failed.")
    return [paths[int(i)] for i in selected[:count]]
