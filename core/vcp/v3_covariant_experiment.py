"""Isolated coupled-alpha V3 first-pass experiment; never imported by production."""

from dataclasses import replace
from time import perf_counter

import numpy as np

from .v2.collision import build_triangle_snapshot
from .v2.contracts import V2Termination
from .v2.structural import _factor_pentadiagonal, _solve_ldlt
from . import v3_experiment as base


V3_COVARIANT_VERSION = "fiber-v3-coupled-alpha-experiment-1"


def solve_v3_covariant(request, snapshot=None, warm_points=(), warm_signature="", fixed_indices=()):
    started = perf_counter(); triangle = snapshot or build_triangle_snapshot(request.colliders)
    corridor = base.plan_v3_corridor(request, triangle)
    if not corridor.succeeded:
        return base._failed_result(corridor)
    state = base._state(request, triangle, corridor, warm_points, warm_signature)
    termination, message, direction_ms, residual = _iterate(state, fixed_indices)
    result = base._finish(state, termination, message, started)
    trace = replace(result.trace, direction_ms=direction_ms, projected_residual=residual)
    return replace(result, trace=trace)


def _iterate(state, fixed_indices=()):
    prior = base._objective(state, state.points); direction_ms = residual = 0.0; rejected = 0
    cap = max(1, state.request.settings.max_accepted_steps)
    while state.accepted < cap and state.iterations < 4 * cap:
        state.iterations += 1; started = perf_counter()
        direction, residual = _direction(state, fixed_indices); direction_ms += base._ms(started)
        accepted, value = base._trial(state, direction, prior)
        if not accepted:
            state.rejected += 1; rejected += 1; state.trust *= 0.5
            if rejected >= 8: return V2Termination.STALLED.value, "coupled trust recovery stalled", direction_ms, residual
            continue
        rejected = 0; state.trust = min(0.35, state.trust * 1.15)
        prior, done = value, _converged(state, prior, value, residual)
        if done: return V2Termination.CONVERGED.value, "coupled alpha solve converged", direction_ms, residual
    return V2Termination.BUDGET_EXHAUSTED.value, "accepted-step cap exhausted", direction_ms, residual


def _direction(state, fixed_indices=()):
    vectors = state.roadmap - state.direct; gradient = base._point_gradient(state, state.points)
    reduced = np.einsum("ij,ij->i", gradient, vectors); active = _active_mask(state, reduced, fixed_indices)
    diagonal, lower1, lower2 = _metric_bands(state, vectors)
    _eliminate_active(diagonal, lower1, lower2, reduced, active)
    factors = _factor_pentadiagonal(diagonal, lower1, lower2)
    direction = _solve_ldlt(*factors, (-reduced)[:, None])[:, 0]
    direction = _bounded_direction(state, direction, vectors)
    direction = base._project_contacts(state, direction, vectors)
    direction = _bounded_direction(state, direction, vectors)
    return direction, _world_residual(direction, vectors, state)


def _active_mask(state, gradient, fixed_indices=()):
    alpha = state.alpha; active = np.zeros(len(alpha), dtype=bool)
    active[np.asarray(state.corridor.pin_indices, dtype=np.int64)] = True
    active[np.asarray(fixed_indices, dtype=np.int64)] = True
    active |= (alpha <= 1.0e-10) & (gradient > 0.0)
    active |= (alpha >= 1.0 - 1.0e-10) & (gradient < 0.0)
    return active


def _metric_bands(state, vectors):
    count = len(vectors); diagonal = np.zeros(count, dtype=np.float64)
    lower1 = np.zeros(count, dtype=np.float64); lower2 = np.zeros(count, dtype=np.float64)
    _add_length_metric(state, vectors, diagonal, lower1)
    _add_curvature_metric(state, vectors, diagonal, lower1, lower2)
    positive = diagonal[diagonal > 1.0e-14]
    damping = max(1.0e-9, 1.0e-3 * float(np.median(positive)) if len(positive) else 1.0e-6)
    diagonal += damping * np.maximum(np.einsum("ij,ij->i", vectors, vectors), 1.0e-6)
    return diagonal, lower1, lower2


def _add_length_metric(state, vectors, diagonal, lower1):
    weight = float(state.request.settings.length_weight)
    for index, edge in enumerate(np.diff(state.points, axis=0)):
        length = max(float(np.linalg.norm(edge)), 1.0e-9); tangent = edge / length
        first, second = vectors[index], vectors[index + 1]
        projected_first = first - tangent * float(np.dot(tangent, first))
        projected_second = second - tangent * float(np.dot(tangent, second))
        diagonal[index] += weight * float(np.dot(first, projected_first)) / length
        diagonal[index + 1] += weight * float(np.dot(second, projected_second)) / length
        lower1[index + 1] -= weight * float(np.dot(second, projected_first)) / length


def _add_curvature_metric(state, vectors, diagonal, lower1, lower2):
    scale = 2.0 * state.request.settings.curvature_weight * base._curvature_factor(state.request, len(vectors))
    for row in range(len(vectors) - 2):
        indices, coefficients = (row, row + 1, row + 2), (1.0, -2.0, 1.0)
        for slot, node in enumerate(indices):
            diagonal[node] += scale * coefficients[slot] ** 2 * float(np.dot(vectors[node], vectors[node]))
        lower1[row + 1] += scale * coefficients[1] * float(np.dot(vectors[row + 1], vectors[row]))
        lower1[row + 2] += scale * coefficients[1] * float(np.dot(vectors[row + 2], vectors[row + 1]))
        lower2[row + 2] += scale * float(np.dot(vectors[row + 2], vectors[row]))


def _eliminate_active(diagonal, lower1, lower2, rhs, active):
    for index in np.flatnonzero(active):
        diagonal[index], rhs[index] = 1.0, 0.0
    for index in range(1, len(diagonal)):
        if active[index] or active[index - 1]: lower1[index] = 0.0
    for index in range(2, len(diagonal)):
        if active[index] or active[index - 2]: lower2[index] = 0.0


def _bounded_direction(state, direction, vectors):
    output = np.clip(np.asarray(direction), -state.alpha, 1.0 - state.alpha)
    widths = np.linalg.norm(vectors, axis=1); nonzero = widths[widths > 1.0e-9]
    width_scale = float(np.median(nonzero)) if len(nonzero) else 1.0
    limit = max(state.request.collision_policy.collision_radius, state.trust * width_scale)
    motion = float(np.max(np.abs(output) * widths)) if len(output) else 0.0
    if motion > limit: output *= limit / motion
    output[np.asarray(state.corridor.pin_indices, dtype=np.int64)] = 0.0
    return output


def _world_residual(direction, vectors, state):
    motion = np.linalg.norm(np.asarray(direction)[:, None] * vectors, axis=1)
    scale = max(state.request.tolerances.length_scale, state.request.collision_policy.collision_radius, 1.0e-9)
    return float(np.max(motion) / scale) if len(motion) else 0.0


def _converged(state, before, after, residual):
    relative = abs(before - after) / max(1.0, abs(before))
    tolerance = state.request.tolerances.relative_energy_tolerance
    return relative < tolerance and residual < max(1.0e-6, tolerance)
