"""Versioned, batched tissue solver interface; no Python numerical fallback."""
from ctypes import POINTER, c_double, c_int
from functools import lru_cache
import numpy as np

from .v2.collision_native import load_native


STATES = ("NOT_APPLICABLE", "CONVERGED", "ITERATION_LIMIT", "INVALID_INPUT", "NUMERICAL_FAILURE", "NATIVE_UNAVAILABLE")
REPORT_FIELDS = ("status", "iterations", "final_change", "max_displacement", "relative_volume_error", "max_fixed_error", "solve_ms")


@lru_cache(maxsize=1)
def library():
    try:
        lib = load_native()
        if not lib.af_fiber_ccd_capabilities() & 536870912 or lib.af_soft_tissue_version() != 1:
            raise RuntimeError("incompatible tissue solver capability/version")
        dp, ip = POINTER(c_double), POINTER(c_int)
        lib.af_soft_tissue_solve.argtypes = [dp, c_int, ip, c_int, dp, dp, dp, c_int, dp, dp, dp]
        lib.af_soft_tissue_solve.restype = c_int
        return lib
    except (OSError, AttributeError, RuntimeError) as exc:
        raise RuntimeError(f"NATIVE_UNAVAILABLE: {exc}") from exc


def parameters(settings, front, tolerance):
    shape = getattr(settings, "shape_retention", getattr(settings, "edge_stiffness", 0.5))
    volume = getattr(settings, "volume_retention", getattr(settings, "volume_stiffness", 0.9))
    return np.asarray((settings.iterations, settings.constraint_passes, front, settings.gravity_step,
        shape, volume, getattr(settings, "seed_fraction", 0.35), getattr(settings, "growth_fraction", 0.55),
        getattr(settings, "velocity_retention", 0.15), getattr(settings, "surface_slack", 0.0),
        getattr(settings, "sag_limit", 0.0), tolerance, *settings.gravity), dtype=np.float64)


def solve(vertices, triangles, fixed, settings, tethers, tolerance, front=0, fixed_goals=None):
    points = np.ascontiguousarray(vertices, dtype=np.float64)
    tri = np.ascontiguousarray(triangles, dtype=np.int32)
    mass, goals = _constraints(points, fixed, fixed_goals)
    rows = np.asarray([(r.vertex_index, *r.anchor, r.rest_length, r.stiffness) for r in tethers], dtype=np.float64)
    config = parameters(settings, front, tolerance)
    _validate_arrays(points, tri, config)
    output, report = np.empty_like(points), np.zeros(7, dtype=np.float64)
    code = library().af_soft_tissue_solve(_dp(points), len(points), tri.ctypes.data_as(POINTER(c_int)),
        len(tri), _dp(mass), _dp(goals), _dp(rows), len(rows), _dp(config), _dp(output), _dp(report))
    if code:
        raise ValueError(STATES[code] if code in (3, 4) else "NUMERICAL_FAILURE")
    values = dict(zip(REPORT_FIELDS, report.tolist()))
    values.update(status=STATES[int(report[0])], iterations=int(report[1]))
    return tuple(map(tuple, output.tolist())), values


def _dp(array):
    return array.ctypes.data_as(POINTER(c_double))


def _constraints(points, fixed, fixed_goals):
    mass, goals = np.ones(len(points), dtype=np.float64), points.copy()
    mass[np.asarray(tuple(fixed), dtype=np.int64)] = 0.0
    for index, goal in dict(fixed_goals or {}).items():
        if not 0 <= index < len(points):
            raise ValueError("INVALID_INPUT: fixed goal index")
        goals[index], mass[index] = goal, 0.0
    return mass, goals


def _validate_arrays(points, triangles, config):
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 4:
        raise ValueError("INVALID_INPUT: tissue coordinates")
    if triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("INVALID_INPUT: tissue triangles")
    if not np.all(np.isfinite(config)) or not np.all(np.isfinite(points)):
        raise ValueError("INVALID_INPUT: nonfinite tissue input")
