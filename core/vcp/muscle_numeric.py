"""Backend-neutral contiguous Muscle surface and inflation contracts."""

from dataclasses import dataclass, replace
from enum import Enum
from os import environ
from time import perf_counter

import numpy as np

from .fiber_surface import build_loft_topology, prepare_loft_rows
from .muscle_inflation_state import INITIALIZED_KEY, WORLD_KEY


MUSCLE_NUMERIC_VERSION = "muscle-numeric-1"


class MuscleNumericBackend(str, Enum):
    PYTHON = "PYTHON"
    NATIVE = "NATIVE"


@dataclass(frozen=True)
class MuscleNumericSpec:
    target_count: int
    densify: bool
    closed_u: bool
    close_across_fibers: bool
    topology_flip_normals: bool
    inflation_enabled: bool
    inflation_mode: str
    inflation_max_value: float
    inflation_falloff_type: str
    inflation_falloff_radius: float
    inflation_direction_depth: float
    inflation_boundary_strength: float
    inflation_boundary_band: float
    inflation_boundary_power: float
    inflation_length_taper_band: float
    closed_v: bool
    flip_normals: bool
    control_world: tuple
    initialize_control: bool = False
    section_profile: object = None
    preserve_samples: bool = False


@dataclass(frozen=True)
class MuscleNumericRequest:
    muscle_id: str
    points: np.ndarray
    spec: MuscleNumericSpec
    orientation_parity: int = 1
    output_domain: object = None


@dataclass(frozen=True)
class MuscleNumericResult:
    muscle_id: str
    base_vertices: np.ndarray
    inflated_vertices: np.ndarray
    faces: np.ndarray
    row_count: int
    column_count: int
    error: str = ""
    source_faces: object = None
    face_parts: object = None


@dataclass(frozen=True)
class MuscleNumericBatchResult:
    results: tuple
    backend: str
    elapsed_ms: float
    workers: int = 1
    parallel: bool = False


def make_muscle_request(muscle_id, points, spec, *, orientation_parity=1, output_domain=None):
    if type(orientation_parity) is not int or orientation_parity not in (-1, 1):
        raise ValueError("PROFILE_PARITY_INVALID: orientation parity must be +1 or -1.")
    array = np.array(points, dtype=np.float64, copy=True, order="C")
    if array.ndim != 3 or array.shape[0] < 2 or array.shape[1] < 2 or array.shape[2] != 3:
        raise ValueError("Muscle input must be a rectangular MxNx3 grid.")
    array.flags.writeable = False
    return MuscleNumericRequest(str(muscle_id), array, spec, orientation_parity, output_domain)


def resolve_muscle_backend(explicit=None, environment=None):
    raw = explicit or dict(environ if environment is None else environment).get("AF_MUSCLE_NUMERIC_BACKEND", "NATIVE")
    try: return MuscleNumericBackend(str(raw).strip().upper())
    except ValueError as error: raise ValueError(f"Invalid Muscle numeric backend: {raw}") from error


def execute_muscle_batch(requests, backend=None):
    from .branched_numeric import BranchedMuscleRequest, execute_mixed
    kind, requests = resolve_muscle_backend(backend), tuple(requests)
    if any(isinstance(r, BranchedMuscleRequest) for r in requests):
        return execute_mixed(requests, kind.value)
    if not requests:
        return MuscleNumericBatchResult((), kind.value, 0.0)
    return _execute_ordinary(requests, kind)


def _execute_ordinary(requests, kind):
    from .muscle_profile_numeric import LEGACY_MODES, execute_partitioned, request_error
    from .muscle_output_domain import apply_batch
    if kind == MuscleNumericBackend.NATIVE:
        from .muscle_numeric_native import execute_native_muscle_batch
        execute = execute_native_muscle_batch
    else:
        execute = execute_python_muscle_batch
    execute = _exact_executor(execute, kind.value)
    if any(request_error(row) or row.spec.inflation_mode not in LEGACY_MODES for row in requests):
        return apply_batch(requests, execute_partitioned(requests, kind.value, execute))
    return apply_batch(requests, execute(requests))


def _exact_executor(ordinary, kind):
    from .free_muscle_numeric import execute
    return lambda requests: execute(requests, kind, ordinary) if any(r.spec.preserve_samples for r in requests) else ordinary(requests)


def execute_python_muscle_batch(requests):
    started = perf_counter()
    results = tuple(_python_result(request) for request in requests)
    elapsed = (perf_counter() - started) * 1000.0
    return MuscleNumericBatchResult(results, MuscleNumericBackend.PYTHON.value, elapsed)


class _InflationAdapter:
    def __init__(self, spec): self._spec = spec
    def __getattr__(self, name): return getattr(self._spec, name)
    def get(self, key, default=None):
        if key == WORLD_KEY: return self._spec.control_world
        return True if key == INITIALIZED_KEY else default


def _python_result(request):
    try: return _python_result_checked(request)
    except Exception as error: return _invalid_result(request.muscle_id, str(error))


def _python_result_checked(request):
    from mathutils import Vector
    spec = request.spec
    rows = prepare_loft_rows(request.points, spec.target_count, spec.closed_u, spec.densify)
    grid = [[Vector(point) for point in row] for row in rows]
    inflated = _inflate_grid(grid, _initialized_spec(grid, spec))
    faces = build_loft_topology(len(grid), len(grid[0]), spec.close_across_fibers,
                                spec.closed_u, spec.topology_flip_normals)
    return _valid_result(request.muscle_id, grid, inflated, faces)


def _initialized_spec(grid, spec):
    if not spec.initialize_control:
        return spec
    point = grid[len(grid) // 2][len(grid[0]) // 2]
    return replace(spec, control_world=(float(point.x), float(point.y), float(point.z)))


def _inflate_grid(grid, spec):
    from ..visualization.muscle_inflation import apply_inflation_distributed, apply_inflation_from_ctrl
    adapter = _InflationAdapter(spec)
    if str(spec.inflation_mode) == "DISTRIBUTED":
        return apply_inflation_distributed(grid, adapter)
    if str(spec.inflation_mode) == "CTRL_POINT":
        return apply_inflation_from_ctrl(grid, adapter)
    raise ValueError("PROFILE_MODE_UNSUPPORTED: " + str(spec.inflation_mode))


def _valid_result(muscle_id, base, inflated, faces):
    rows, columns = len(base), len(base[0])
    base_array = _readonly_array(base, np.float64, (-1, 3))
    infl_array = _readonly_array(inflated, np.float64, (-1, 3))
    face_array = _readonly_array(faces, np.int64, (-1, 4))
    return MuscleNumericResult(muscle_id, base_array, infl_array, face_array, rows, columns)


def _readonly_array(values, dtype, shape):
    array = np.ascontiguousarray(values, dtype=dtype).reshape(shape)
    array.flags.writeable = False
    return array


def _invalid_result(muscle_id, error):
    points = _readonly_array((), np.float64, (0, 3))
    faces = _readonly_array((), np.int64, (0, 4))
    return MuscleNumericResult(str(muscle_id), points, points, faces, 0, 0, str(error))
