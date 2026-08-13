from dataclasses import dataclass
from importlib.util import find_spec
import os
import platform
import sys

import numpy as np


_EPSILON = 128.0 * np.finfo(np.float64).eps
_PILOT_ENV = "ANTHROFORGE_FIBER_CCD_PILOT"


@dataclass(frozen=True)
class PrimitiveSweepResult:
    safe_step: float
    toi_upper: float
    clearance_at_safe_step: float
    minimum_sampled_distance: float
    possible_collision: bool
    initially_valid: bool
    intervals: int
    reason: str


@dataclass(frozen=True)
class MeshSweepResult:
    safe_step: float
    possible_collision: bool
    initially_valid: bool
    candidate_pairs: int
    tested_pairs: int
    intervals: int
    reason: str


@dataclass(frozen=True)
class IpcEnvironmentReport:
    requested_backend: str
    python_tag: str
    platform_tag: str
    numpy_available: bool
    scipy_available: bool
    ipctk_available: bool
    known_wheel_supported: bool
    legal_review_required: bool
    production_eligible: bool


@dataclass(frozen=True)
class _SweepContext:
    start: np.ndarray
    end: np.ndarray
    triangle: np.ndarray
    clearance: float
    speed: float
    guard: float


@dataclass
class _SearchState:
    stack: list
    safe_until: float
    minimum_distance: float
    intervals: int = 0


@dataclass
class _MeshState:
    safe_step: float = 1.0
    possible_collision: bool = False
    initially_valid: bool = True
    candidate_pairs: int = 0
    tested_pairs: int = 0
    intervals: int = 0


def _point(value, name):
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (3,):
        raise ValueError(f"{name} must have shape (3,)")
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must contain finite coordinates")
    return result


def _triangle(value):
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (3, 3):
        raise ValueError("triangle must have shape (3, 3)")
    if not np.all(np.isfinite(result)):
        raise ValueError("triangle must contain finite coordinates")
    return result


def _nonnegative(value, name):
    result = float(value)
    if not np.isfinite(result) or result < 0.0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return result


def _point_segment_distance(point, start, end):
    direction = end - start
    length_sq = float(np.dot(direction, direction))
    if length_sq <= _EPSILON:
        return float(np.linalg.norm(point - start))
    fraction = np.clip(np.dot(point - start, direction) / length_sq, 0.0, 1.0)
    return float(np.linalg.norm(point - (start + fraction * direction)))


def _projection_inside(point, triangle):
    first, second, third = triangle
    edge_a, edge_b, offset = second - first, third - first, point - first
    aa, ab, bb = np.dot(edge_a, edge_a), np.dot(edge_a, edge_b), np.dot(edge_b, edge_b)
    ap, bp = np.dot(offset, edge_a), np.dot(offset, edge_b)
    determinant = aa * bb - ab * ab
    if determinant <= _EPSILON * max(1.0, aa * bb):
        return False
    u, v = (bb * ap - ab * bp) / determinant, (aa * bp - ab * ap) / determinant
    return u >= -_EPSILON and v >= -_EPSILON and u + v <= 1.0 + _EPSILON


def _point_triangle_distance(point, triangle):
    first, second, third = triangle
    normal = np.cross(second - first, third - first)
    normal_sq = float(np.dot(normal, normal))
    if normal_sq > _EPSILON:
        signed = float(np.dot(point - first, normal)) / normal_sq
        projection = point - signed * normal
        if _projection_inside(projection, triangle):
            return abs(signed) * np.sqrt(normal_sq)
    edges = ((first, second), (second, third), (third, first))
    return min(_point_segment_distance(point, *edge) for edge in edges)


def _interior_segment_distance(first_a, first_b, second_a, second_b):
    first, second, offset = first_b - first_a, second_b - second_a, first_a - second_a
    aa, ab, bb = np.dot(first, first), np.dot(first, second), np.dot(second, second)
    ao, bo = np.dot(first, offset), np.dot(second, offset)
    determinant = aa * bb - ab * ab
    if determinant <= _EPSILON * max(1.0, aa * bb):
        return np.inf
    s, t = (ab * bo - bb * ao) / determinant, (aa * bo - ab * ao) / determinant
    if not (0.0 <= s <= 1.0 and 0.0 <= t <= 1.0):
        return np.inf
    return float(np.linalg.norm(first_a + s * first - second_a - t * second))


def _segment_segment_distance(first_a, first_b, second_a, second_b):
    candidates = [_interior_segment_distance(first_a, first_b, second_a, second_b)]
    candidates.append(_point_segment_distance(first_a, second_a, second_b))
    candidates.append(_point_segment_distance(first_b, second_a, second_b))
    candidates.append(_point_segment_distance(second_a, first_a, first_b))
    candidates.append(_point_segment_distance(second_b, first_a, first_b))
    return min(candidates)


def _segment_hits_triangle(start, end, triangle):
    first, second, third = triangle
    direction, edge_a, edge_b = end - start, second - first, third - first
    cross = np.cross(direction, edge_b)
    determinant = float(np.dot(edge_a, cross))
    scale = max(1.0, np.linalg.norm(direction) * np.linalg.norm(edge_a) * np.linalg.norm(edge_b))
    if abs(determinant) <= _EPSILON * scale:
        return False
    offset, inverse = start - first, 1.0 / determinant
    u = float(np.dot(offset, cross)) * inverse
    cross_offset = np.cross(offset, edge_a)
    v = float(np.dot(direction, cross_offset)) * inverse
    fraction = float(np.dot(edge_b, cross_offset)) * inverse
    return u >= -_EPSILON and v >= -_EPSILON and u + v <= 1.0 + _EPSILON and -_EPSILON <= fraction <= 1.0 + _EPSILON


def segment_triangle_distance(start, end, triangle):
    start, end, triangle = _point(start, "start"), _point(end, "end"), _triangle(triangle)
    if _segment_hits_triangle(start, end, triangle):
        return 0.0
    distances = [_point_triangle_distance(start, triangle), _point_triangle_distance(end, triangle)]
    for index in range(3):
        distances.append(_segment_segment_distance(start, end, triangle[index], triangle[(index + 1) % 3]))
    return float(min(distances))


def _make_context(start, end, triangle, clearance):
    start = np.asarray(start, dtype=np.float64)
    end = np.asarray(end, dtype=np.float64)
    if start.shape != (2, 3) or end.shape != (2, 3):
        raise ValueError("start and end segments must have shape (2, 3)")
    if not np.all(np.isfinite(start)) or not np.all(np.isfinite(end)):
        raise ValueError("segment motion must contain finite coordinates")
    triangle, clearance = _triangle(triangle), _nonnegative(clearance, "clearance")
    speed = float(np.max(np.linalg.norm(end - start, axis=1)))
    scale = max(1.0, float(np.max(np.abs(np.vstack((start, end, triangle))))))
    return _SweepContext(start, end, triangle, clearance, speed, _EPSILON * scale)


def _segment_at(context, time):
    return context.start + float(time) * (context.end - context.start)


def _distance_at(context, time):
    segment = _segment_at(context, time)
    return segment_triangle_distance(segment[0], segment[1], context.triangle)


def _swept_bounds_overlap(context):
    moving = np.vstack((context.start, context.end))
    padding = context.clearance + context.guard
    moving_min, moving_max = np.min(moving, axis=0) - padding, np.max(moving, axis=0) + padding
    triangle_min, triangle_max = np.min(context.triangle, axis=0), np.max(context.triangle, axis=0)
    return bool(np.all(moving_max >= triangle_min) and np.all(triangle_max >= moving_min))


def _primitive_result(context, safe_step, upper, minimum, collision, valid, intervals, reason):
    clearance = _distance_at(context, safe_step)
    return PrimitiveSweepResult(float(safe_step), float(upper), clearance, float(minimum), collision, valid, intervals, reason)


def _certified_interval(context, lower, upper):
    midpoint = 0.5 * (lower + upper)
    distance = _distance_at(context, midpoint)
    bound = distance - context.speed * 0.5 * (upper - lower) - context.guard
    return bound > context.clearance, distance


def _possible_result(context, state, upper, reason):
    return _primitive_result(context, state.safe_until, upper, state.minimum_distance, True, True, state.intervals, reason)


def _subdivide_sweep(context, start_distance, time_tolerance, max_intervals):
    state = _SearchState([(0.0, 1.0)], 0.0, start_distance)
    while state.stack:
        if state.intervals >= max_intervals:
            return _possible_result(context, state, state.stack[-1][1], "BUDGET_EXHAUSTED")
        lower, upper = state.stack.pop()
        certified, distance = _certified_interval(context, lower, upper)
        state.intervals += 1; state.minimum_distance = min(state.minimum_distance, distance)
        if certified:
            state.safe_until = max(state.safe_until, upper); continue
        if upper - lower <= time_tolerance:
            return _possible_result(context, state, upper, "POSSIBLE_COLLISION")
        midpoint = 0.5 * (lower + upper)
        state.stack.extend(((midpoint, upper), (lower, midpoint)))
    return _primitive_result(context, 1.0, 1.0, state.minimum_distance, False, True, state.intervals, "CLEAR")


def swept_segment_triangle_reference(start, end, triangle, clearance=0.0, time_tolerance=1.0e-5, max_intervals=262143):
    context = _make_context(start, end, triangle, clearance)
    time_tolerance = _nonnegative(time_tolerance, "time_tolerance")
    if time_tolerance == 0.0 or int(max_intervals) < 1:
        raise ValueError("time_tolerance and max_intervals must be positive")
    start_distance = _distance_at(context, 0.0)
    if start_distance <= context.clearance + context.guard:
        return _primitive_result(context, 0.0, 0.0, start_distance, True, False, 0, "INVALID_START")
    if not _swept_bounds_overlap(context):
        return _primitive_result(context, 1.0, 1.0, start_distance, False, True, 0, "AABB_CLEAR")
    if context.speed <= context.guard:
        return _primitive_result(context, 1.0, 1.0, start_distance, False, True, 0, "STATIC_CLEAR")
    return _subdivide_sweep(context, start_distance, time_tolerance, int(max_intervals))


def _mesh_inputs(start_points, end_points, edges, vertices, triangles):
    start, end = np.asarray(start_points, dtype=np.float64), np.asarray(end_points, dtype=np.float64)
    edges, vertices, triangles = np.asarray(edges, dtype=np.int64), np.asarray(vertices, dtype=np.float64), np.asarray(triangles, dtype=np.int64)
    if start.shape != end.shape or start.ndim != 2 or start.shape[1] != 3:
        raise ValueError("start_points and end_points must have equal shape (N, 3)")
    if edges.ndim != 2 or edges.shape[1] != 2 or vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError("edges and vertices must have shapes (E, 2) and (V, 3)")
    if triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("triangles must have shape (T, 3)")
    if not np.all(np.isfinite(start)) or not np.all(np.isfinite(end)) or not np.all(np.isfinite(vertices)):
        raise ValueError("mesh sweep coordinates must be finite")
    return start, end, edges, vertices, triangles


def _candidate_faces(start, end, triangle_bounds, padding):
    moving = np.vstack((start, end))
    lower, upper = np.min(moving, axis=0) - padding, np.max(moving, axis=0) + padding
    triangle_min, triangle_max = triangle_bounds
    overlap = np.all(triangle_max >= lower, axis=1) & np.all(triangle_min <= upper, axis=1)
    return np.flatnonzero(overlap)


def _absorb_primitive(state, result):
    state.tested_pairs += 1
    state.intervals += result.intervals
    state.initially_valid = state.initially_valid and result.initially_valid
    state.possible_collision = state.possible_collision or result.possible_collision
    state.safe_step *= result.safe_step


def _sweep_edge(state, edge_index, edge, start, end, triangle_data, clearance, pair_filter):
    triangle_vertices, triangle_bounds, padding = triangle_data
    scaled_end = start[edge] + state.safe_step * (end[edge] - start[edge])
    candidates = _candidate_faces(start[edge], scaled_end, triangle_bounds, padding)
    state.candidate_pairs += len(candidates)
    for triangle_index in candidates:
        if pair_filter is not None and not pair_filter(edge_index, int(triangle_index)):
            continue
        result = swept_segment_triangle_reference(start[edge], scaled_end, triangle_vertices[triangle_index], clearance)
        _absorb_primitive(state, result)
        if not state.initially_valid or state.safe_step == 0.0:
            return False
        scaled_end = start[edge] + state.safe_step * (end[edge] - start[edge])
    return True


def _mesh_result(state):
    if not state.initially_valid:
        reason = "INVALID_START"
    elif state.possible_collision:
        reason = "POSSIBLE_COLLISION"
    else:
        reason = "CLEAR"
    return MeshSweepResult(state.safe_step, state.possible_collision, state.initially_valid,
                           state.candidate_pairs, state.tested_pairs, state.intervals, reason)


def mesh_collision_free_step_reference(start_points, end_points, edges, vertices, triangles, clearance=0.0, pair_filter=None):
    start, end, edges, vertices, triangles = _mesh_inputs(start_points, end_points, edges, vertices, triangles)
    clearance = _nonnegative(clearance, "clearance")
    if np.any(edges < 0) or np.any(edges >= len(start)):
        raise ValueError("edge index is out of range")
    if np.any(triangles < 0) or np.any(triangles >= len(vertices)):
        raise ValueError("triangle index is out of range")
    triangle_vertices = vertices[triangles]
    triangle_bounds = np.min(triangle_vertices, axis=1), np.max(triangle_vertices, axis=1)
    scale = max(1.0, float(np.max(np.abs(start), initial=0.0)), float(np.max(np.abs(end), initial=0.0)), float(np.max(np.abs(vertices), initial=0.0)))
    triangle_data = triangle_vertices, triangle_bounds, clearance + _EPSILON * scale
    state = _MeshState()
    for edge_index, edge in enumerate(edges):
        if not _sweep_edge(state, edge_index, edge, start, end, triangle_data, clearance, pair_filter):
            break
    return _mesh_result(state)


def pilot_backend(environment=None):
    environment = os.environ if environment is None else environment
    requested = str(environment.get(_PILOT_ENV, "")).strip().lower()
    return requested if requested in {"reference", "ipctk"} else "disabled"


def _module_available(name):
    try:
        return find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _known_wheel_supported(system, machine, python_tag):
    system, machine = system.lower(), machine.lower()
    supported = (("windows", "amd64"), ("linux", "x86_64"), ("darwin", "arm64"))
    return python_tag == "cp311" and (system, machine) in supported


def ipc_environment_report(environment=None):
    requested = pilot_backend(environment)
    python_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    system, machine = platform.system(), platform.machine()
    numpy_ready, scipy_ready = _module_available("numpy"), _module_available("scipy")
    ipc_ready = _module_available("ipctk")
    wheel_ready = _known_wheel_supported(system, machine, python_tag)
    return IpcEnvironmentReport(requested, python_tag, f"{system}-{machine}", numpy_ready,
                                scipy_ready, ipc_ready, wheel_ready, True, False)


def pilot_swept_segment_triangle(start, end, triangle, clearance=0.0, environment=None):
    backend = pilot_backend(environment)
    if backend == "reference":
        return swept_segment_triangle_reference(start, end, triangle, clearance)
    if backend == "ipctk":
        raise RuntimeError("IPC Toolkit pilot is not approved for packaging or production")
    raise RuntimeError(f"CCD pilot is disabled; set {_PILOT_ENV}=reference for development")
