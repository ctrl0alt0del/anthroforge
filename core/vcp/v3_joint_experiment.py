"""Isolated joint in-surface/transverse V3 refinement experiment."""

from dataclasses import dataclass, field
from time import perf_counter

import numpy as np

from .v2.collision import V2SweepPairCache, build_triangle_snapshot, collision_free_step
from .v2.contracts import V2Termination
from . import v3_experiment as base
from . import v3_transverse_experiment as transverse


V3_JOINT_VERSION = "fiber-v3-joint-corridor-experiment-1"


@dataclass(frozen=True)
class V3JointResult:
    points: tuple = ()
    alpha: tuple = ()
    beta: tuple = ()
    valid: bool = False
    termination: str = V2Termination.INVALID_CONFIGURATION.value
    message: str = ""
    length: float = 0.0
    curvature: float = 0.0
    objective: float = 0.0
    corridor: object = None
    trace: object = field(default_factory=base.V3Trace)


@dataclass
class _JointState:
    request: object
    snapshot: object
    corridor: object
    direct: np.ndarray
    ribbon: np.ndarray
    normal: np.ndarray
    low: np.ndarray
    high: np.ndarray
    coordinates: np.ndarray
    points: np.ndarray
    edges: np.ndarray
    world: object
    pair_cache: object
    trust: float = 0.2
    iterations: int = 0
    accepted: int = 0
    rejected: int = 0
    contacts: int = 0
    ccd: int = 0


def solve_v3_joint(request, snapshot=None, first_pass=None):
    started = perf_counter(); triangle = snapshot or build_triangle_snapshot(request.colliders)
    prior = first_pass or base.solve_v3_corridor(request, triangle)
    if not prior.valid: return _failed(prior, "scalar first pass is invalid")
    state, interval_ms = _state(request, triangle, prior)
    termination, message, direction_ms, residual = _iterate(state)
    return _finish(state, prior, termination, message, started, interval_ms, direction_ms, residual)


def _state(request, snapshot, prior):
    started = perf_counter(); normal = transverse._frame(prior)
    active = transverse._active_mask(prior.points, prior.corridor.pin_indices, "full")
    bounds, _stats = transverse._bounds(request, prior, normal, active); low, high, normal = bounds
    direct = np.asarray(prior.corridor.direct); ribbon = np.asarray(prior.corridor.roadmap) - direct
    coordinates = np.column_stack((np.asarray(prior.alpha), np.zeros(len(direct))))
    state = _JointState(request, snapshot, prior.corridor, direct, ribbon, normal, low, high,
                        coordinates, np.asarray(prior.points), base._edges(len(direct)),
                        base._world(request), V2SweepPairCache())
    return state, base._ms(started)


def _iterate(state):
    prior = base._objective(state, state.points); direction_ms = residual = 0.0; rejected = 0
    cap = max(1, state.request.settings.max_accepted_steps)
    while state.accepted < cap and state.iterations < 4 * cap:
        state.iterations += 1; started = perf_counter(); direction, residual = _direction(state)
        direction_ms += base._ms(started); accepted, value = _trial(state, direction, prior)
        if not accepted:
            state.rejected += 1; rejected += 1; state.trust *= 0.5
            if rejected >= 8: return V2Termination.STALLED.value, "joint trust recovery stalled", direction_ms, residual
            continue
        rejected = 0; state.trust = min(0.35, state.trust * 1.15); prior = value
        if residual < 1.0e-6: return V2Termination.CONVERGED.value, "joint corridor converged", direction_ms, residual
    return V2Termination.BUDGET_EXHAUSTED.value, "accepted-step cap exhausted", direction_ms, residual


def _direction(state):
    basis = _basis(state); gradient = base._point_gradient(state, state.points)
    reduced = np.einsum("nij,ni->nj", basis, gradient); matrix = _metric(state, basis)
    active = _active(state, reduced); rhs = -reduced.reshape(-1)
    _eliminate(matrix, rhs, active.reshape(-1)); direction = np.linalg.solve(matrix, rhs).reshape((-1, 2))
    direction = _bounded(state, direction, basis)
    direction = _project_contacts(state, direction, basis)
    direction = _bounded(state, direction, basis)
    return direction, _residual(state, direction, basis)


def _basis(state):
    return np.stack((state.ribbon, state.normal), axis=2)


def _metric(state, basis):
    size = 2 * len(basis); matrix = np.zeros((size, size), dtype=np.float64)
    _add_length(state, basis, matrix); _add_curvature(state, basis, matrix)
    diagonal = np.diag(matrix); positive = diagonal[diagonal > 1.0e-14]
    damping = max(1.0e-9, 1.0e-3 * float(np.median(positive)) if len(positive) else 1.0e-6)
    matrix.flat[::size + 1] += damping
    return matrix


def _add_length(state, basis, matrix):
    weight = float(state.request.settings.length_weight)
    for index, edge in enumerate(np.diff(state.points, axis=0)):
        length = max(float(np.linalg.norm(edge)), 1.0e-9); tangent = edge / length
        projector = np.eye(3) - np.outer(tangent, tangent)
        _add_block(matrix, index, index, weight * basis[index].T @ projector @ basis[index] / length)
        _add_block(matrix, index + 1, index + 1, weight * basis[index + 1].T @ projector @ basis[index + 1] / length)
        block = -weight * basis[index].T @ projector @ basis[index + 1] / length
        _add_symmetric(matrix, index, index + 1, block)


def _add_curvature(state, basis, matrix):
    scale = 2.0 * state.request.settings.curvature_weight * base._curvature_factor(state.request, len(basis))
    for row in range(len(basis) - 2):
        indices, coefficients = (row, row + 1, row + 2), (1.0, -2.0, 1.0)
        for first, node in enumerate(indices):
            for second in range(first, 3):
                other = indices[second]; block = scale * coefficients[first] * coefficients[second] * basis[node].T @ basis[other]
                if node == other: _add_block(matrix, node, other, block)
                else: _add_symmetric(matrix, node, other, block)


def _add_block(matrix, first, second, block):
    matrix[2 * first:2 * first + 2, 2 * second:2 * second + 2] += block


def _add_symmetric(matrix, first, second, block):
    _add_block(matrix, first, second, block)
    _add_block(matrix, second, first, block.T)


def _active(state, gradient):
    values = state.coordinates; active = np.zeros_like(values, dtype=bool)
    active[np.asarray(state.corridor.pin_indices, dtype=np.int64)] = True
    active[:, 0] |= (values[:, 0] <= 1.0e-10) & (gradient[:, 0] > 0.0)
    active[:, 0] |= (values[:, 0] >= 1.0 - 1.0e-10) & (gradient[:, 0] < 0.0)
    active[:, 1] |= (values[:, 1] <= state.low + 1.0e-10) & (gradient[:, 1] > 0.0)
    active[:, 1] |= (values[:, 1] >= state.high - 1.0e-10) & (gradient[:, 1] < 0.0)
    return active


def _eliminate(matrix, rhs, active):
    for index in np.flatnonzero(active):
        matrix[index, :], matrix[:, index] = 0.0, 0.0
        matrix[index, index], rhs[index] = 1.0, 0.0


def _bounded(state, direction, basis):
    low = np.column_stack((-state.coordinates[:, 0], state.low - state.coordinates[:, 1]))
    high = np.column_stack((1.0 - state.coordinates[:, 0], state.high - state.coordinates[:, 1]))
    output = np.clip(np.asarray(direction), low, high); motion = np.einsum("nij,nj->ni", basis, output)
    widths = np.linalg.norm(state.ribbon, axis=1); nonzero = widths[widths > 1.0e-9]
    limit = max(state.request.collision_policy.collision_radius,
                state.trust * (float(np.median(nonzero)) if len(nonzero) else 1.0))
    maximum = float(np.max(np.linalg.norm(motion, axis=1))) if len(motion) else 0.0
    if maximum > limit: output *= limit / maximum
    output[np.asarray(state.corridor.pin_indices, dtype=np.int64)] = 0.0
    return output


def _project_contacts(state, direction, basis):
    threshold = base._threshold(state); band = _contact_band(state)
    rows, mapping = base._chain_contacts(state, state.points, threshold + band); state.contacts += 1
    output = np.asarray(direction).copy()
    for _pass in range(3):
        for query, enabled in enumerate(rows.active):
            if enabled: _project_row(output, basis, state.edges, rows, mapping, query, threshold + band)
    return output


def _contact_band(state):
    return max(0.5 * state.request.collision_policy.collision_radius,
               2.0 * state.request.tolerances.clearance_slack)


def _project_row(direction, basis, edges, rows, mapping, query, target):
    edge, low, high = mapping[query]; factor = low + (high - low) * rows.factors[query]
    first, second = map(int, edges[edge]); weights = (1.0 - factor, factor)
    coefficients = np.concatenate((weights[0] * basis[first].T @ rows.normals[query],
                                   weights[1] * basis[second].T @ rows.normals[query]))
    values = np.concatenate((direction[first], direction[second])); movement = float(np.dot(coefficients, values))
    required = max(0.0, float(target) - float(rows.distances[query])); scale = float(np.dot(coefficients, coefficients))
    if movement < required and scale > 1.0e-18:
        values += (required - movement) * coefficients / scale
        direction[first], direction[second] = values[:2], values[2:]


def _trial(state, direction, prior):
    target_coordinates = state.coordinates + direction; target = _points(state, target_coordinates)
    step = collision_free_step(state.points, target, state.snapshot, state.request.collision_policy.collision_radius,
                               state.corridor.contacts, slack=state.request.tolerances.clearance_slack,
                               pair_cache=state.pair_cache, assume_initial_valid=True)
    state.ccd += 1
    if not step.valid or step.safe_step <= 1.0e-10: return False, prior
    fraction = 1.0 if step.safe_step >= 1.0 else 0.999 * step.safe_step
    return _line_search(state, fraction * direction, prior)


def _line_search(state, direction, prior):
    for depth in range(8):
        coordinates = state.coordinates + (0.5 ** depth) * direction; points = _points(state, coordinates)
        value = base._objective(state, points)
        if value < prior - 1.0e-10 * max(1.0, prior):
            state.coordinates, state.points = coordinates, points; state.accepted += 1
            return True, value
    return False, prior


def _points(state, coordinates):
    return state.direct + coordinates[:, :1] * state.ribbon + coordinates[:, 1:] * state.normal


def _residual(state, direction, basis):
    motion = np.linalg.norm(np.einsum("nij,nj->ni", basis, direction), axis=1)
    scale = max(state.request.tolerances.length_scale, state.request.collision_policy.collision_radius, 1.0e-9)
    return float(np.max(motion) / scale) if len(motion) else 0.0


def _finish(state, prior, termination, message, started, interval_ms, direction_ms, residual):
    validation = perf_counter(); valid = base._exact_valid(state.request, state.snapshot, state.corridor, state.points)
    validation_ms = base._ms(validation); length, curvature, objective = base._metrics(state, state.points)
    reason = termination if valid else V2Termination.UNSAFE_OUTPUT.value
    text = message if valid else "joint candidate failed independent validation"
    trace = base.V3Trace(state.iterations, state.accepted, state.rejected, state.contacts, state.ccd,
                         state.corridor.planner_ms, base._ms(started) - validation_ms, validation_ms,
                         interval_ms, warm_start=False, direction_ms=direction_ms, projected_residual=residual)
    return V3JointResult(base._tuples(state.points), tuple(state.coordinates[:, 0]),
                         tuple(state.coordinates[:, 1]), valid, reason, text, length, curvature,
                         objective, state.corridor, trace)


def _failed(prior, message):
    return V3JointResult(points=prior.points, valid=False, termination=prior.termination,
                         message=message, corridor=prior.corridor)
