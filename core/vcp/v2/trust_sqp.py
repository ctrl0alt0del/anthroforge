"""Accepted active-set trust-region step shared by Fiber V2 and V3."""

from dataclasses import dataclass, replace
from time import perf_counter

import numpy as np

from .collision_native import native_structural_contact_responses
from .structural import _base_bands, _normal_gradient, _static_settings, structural_energy


@dataclass(frozen=True)
class V2TrustSqpStep:
    points: np.ndarray
    active_keys: tuple
    multipliers: tuple
    predicted_violation: float
    predicted_energy: float
    normal_norm: float
    tangential_norm: float
    solve_ms: float
    condition: float
    regularization: float = 0.0
    structural_condition: float = 0.0
    constraint_condition: float = 0.0


def solve_trust_sqp(points, reference, settings, contacts, pins, trust_radius,
                    true_length_epsilon=None, spacing_weight=0.0, regularization=0.0):
    started = perf_counter(); rows = _linear_contacts(points, contacts)
    problem = _native_problem(points, reference, settings, contacts, pins,
                              true_length_epsilon, spacing_weight, regularization)
    solved = _active_set(problem[0], problem[1], rows, np.asarray(points).reshape(-1))
    candidate = solved[0].reshape((-1, 3))
    candidate = _trust_limited(points, candidate, pins, trust_radius)
    normal, tangent = _step_components(points, candidate, rows, solved[1])
    violation = _linearized_violation(points, candidate, rows)
    energy = objective_energy(candidate, reference, settings, true_length_epsilon, spacing_weight).total
    elapsed = 1000.0 * (perf_counter() - started)
    return V2TrustSqpStep(candidate, solved[2], tuple(solved[3]), violation, energy,
        normal, tangent, elapsed, max(problem[2]["condition"], solved[4]), regularization=regularization,
        structural_condition=problem[2]["condition"], constraint_condition=solved[4])


def update_trust_radius(radius, minimum, maximum, ratio, accepted, boundary, contact_changed=False):
    if contact_changed: return max(minimum, min(maximum, radius))
    if not accepted or not np.isfinite(ratio) or ratio < .1: return max(minimum, .25 * radius)
    if ratio < .25: return max(minimum, .5 * radius)
    if ratio > .75 and boundary: return min(maximum, 2.0 * radius)
    return max(minimum, min(maximum, radius))


def model_reduction(points, candidate, reference, settings, contacts, pins, feasible,
                    true_length_epsilon=None, spacing_weight=0.0, regularization=0.0):
    if feasible:
        before = _model_energy(points, points, reference, settings, true_length_epsilon, spacing_weight)
        after = _model_energy(candidate, points, reference, settings, true_length_epsilon, spacing_weight)
        return before - after - _proximal_energy(candidate, points, regularization)
    rows = _linear_contacts(points, contacts)
    return _contact_merit(rows, points, points) - _contact_merit(rows, points, candidate)


def actual_reduction(before, after, energy_before, energy_after, feasible):
    if feasible: return float(energy_before - energy_after)
    return _feasibility_merit(before) - _feasibility_merit(after)


def _native_problem(points, reference, settings, contacts, pins, epsilon=None,
                    spacing_weight=0.0, regularization=0.0):
    count = len(reference); bands = _objective_bands(points, settings, epsilon)
    rhs = settings.fidelity_weight * np.asarray(reference, dtype=np.float64)
    bands, rhs = _spacing_model(bands, rhs, points, spacing_weight)
    bands, rhs = _proximal_model(bands, rhs, points, regularization)
    rows = tuple((row.edge, row.factor, row.normal) for row in contacts)
    indices = tuple(sorted(pins)); targets = tuple(pins[index] for index in indices)
    return native_structural_contact_responses(bands, rhs, rows, indices, targets)


def _proximal_model(bands, rhs, points, weight):
    if weight <= 0.0: return bands, rhs
    diagonal, lower1, lower2 = (value.copy() for value in bands)
    diagonal += float(weight); target = np.asarray(rhs) + float(weight) * np.asarray(points)
    return (diagonal, lower1, lower2), target


def _proximal_energy(values, center, weight):
    delta = np.asarray(values, dtype=np.float64) - np.asarray(center, dtype=np.float64)
    return max(0.0, float(weight)) * float(np.sum(delta * delta))


def objective_energy(points, reference, settings, epsilon=None, spacing_weight=0.0):
    base = _length_energy(points, reference, settings, epsilon)
    spacing = _spacing_energy(points, spacing_weight)
    return replace(base, fidelity=base.fidelity + spacing)


def objective_gradient(points, reference, settings, epsilon=None, spacing_weight=0.0):
    gradient = _length_gradient(points, reference, settings, epsilon)
    return gradient + _spacing_gradient(points, spacing_weight)


def objective_diagonal(points, settings, epsilon=None, spacing_weight=0.0):
    return _objective_bands(points, settings, epsilon)[0] + float(spacing_weight)


def _length_energy(points, reference, settings, epsilon):
    if epsilon is None: return structural_energy(points, reference, settings)
    base = structural_energy(points, reference, replace(settings, length_weight=0.0))
    lengths = _edge_lengths(np.diff(np.asarray(points, dtype=np.float64), axis=0), epsilon)
    return replace(base, length=float(settings.length_weight) * float(np.sum(lengths)))


def _length_gradient(points, reference, settings, epsilon):
    if epsilon is None: return _quadratic_gradient(points, reference, settings)
    gradient = _quadratic_gradient(points, reference, replace(settings, length_weight=0.0))
    edges = np.diff(np.asarray(points, dtype=np.float64), axis=0)
    scaled = .5 * float(settings.length_weight) * edges / _edge_lengths(edges, epsilon)[:, None]
    gradient[:-1] -= scaled; gradient[1:] += scaled
    return gradient


def _spacing_model(bands, rhs, points, weight):
    if weight <= 0.0: return bands, rhs
    diagonal, lower1, lower2 = (value.copy() for value in bands)
    diagonal += float(weight)
    target = np.asarray(rhs) + float(weight) * np.asarray(points)
    target -= _spacing_gradient(points, weight)
    return (diagonal, lower1, lower2), target


def _spacing_energy(points, weight):
    lengths = np.linalg.norm(np.diff(np.asarray(points), axis=0), axis=1)
    if weight <= 0.0 or not len(lengths): return 0.0
    return float(weight) * float(np.sum((lengths - np.mean(lengths)) ** 2))


def _spacing_gradient(points, weight):
    values = np.asarray(points, dtype=np.float64); output = np.zeros_like(values)
    edges = np.diff(values, axis=0); lengths = np.linalg.norm(edges, axis=1)
    if weight <= 0.0 or not len(lengths): return output
    units = np.divide(edges, lengths[:, None], out=np.zeros_like(edges), where=lengths[:, None] > 1.0e-15)
    scaled = float(weight) * (lengths - np.mean(lengths))[:, None] * units
    output[:-1] -= scaled; output[1:] += scaled
    return output


def _quadratic_gradient(points, reference, settings):
    return _normal_gradient(np.asarray(points), np.asarray(reference), _static_settings(settings))


def _objective_bands(points, settings, epsilon):
    if epsilon is None: return _base_bands(len(points), _static_settings(settings))
    base = _base_bands(len(points), _static_settings(replace(settings, length_weight=0.0)))
    return _add_weighted_length(base, _edge_scales(points, settings, epsilon))


def _add_weighted_length(bands, scales):
    diagonal, lower1, lower2 = (value.copy() for value in bands)
    diagonal[:-1] += scales; diagonal[1:] += scales; lower1[1:] -= scales
    return diagonal, lower1, lower2


def _edge_scales(points, settings, epsilon):
    edges = np.diff(np.asarray(points, dtype=np.float64), axis=0)
    return .5 * float(settings.length_weight) / _edge_lengths(edges, epsilon)


def _edge_lengths(edges, epsilon):
    return np.sqrt(np.sum(edges * edges, axis=1) + float(epsilon) ** 2)


def _model_energy(values, linearization, reference, settings, epsilon, spacing_weight=0.0):
    if epsilon is None:
        return structural_energy(values, reference, settings).total + _spacing_energy(values, spacing_weight)
    base = structural_energy(values, reference, replace(settings, length_weight=0.0)).total
    edges = np.diff(np.asarray(values), axis=0); scales = _edge_scales(linearization, settings, epsilon)
    return float(base + np.sum(scales * np.sum(edges * edges, axis=1)) +
                 _spacing_energy(values, spacing_weight))


def _linear_contacts(points, contacts):
    output = []
    for row in contacts:
        jacobian = _contact_jacobian(len(points), row)
        gap = row.linearized_gap if np.isfinite(row.linearized_gap) else row.gap
        output.append((row.key, jacobian, float(gap), float(row.multiplier)))
    return tuple(output)


def _contact_jacobian(count, contact):
    output = np.zeros(3 * count); normal = np.asarray(contact.normal, dtype=np.float64)
    output[3 * contact.edge:3 * contact.edge + 3] = (1.0 - contact.factor) * normal
    output[3 * contact.edge + 3:3 * contact.edge + 6] = contact.factor * normal
    return output


def _active_set(base, responses, rows, current):
    base = np.asarray(base).reshape(-1)
    response = np.empty((len(base), 0)) if not rows else np.asarray(responses).reshape((len(rows), -1)).T
    active = [index for index, row in enumerate(rows) if row[2] <= 0.0 or row[3] > 0.0]
    for _iteration in range(min(16, max(4, 2 * len(rows) + 1))):
        solved = _equality_solution(base, response, rows, active, current)
        change = _active_change(rows, active, solved[0], current, solved[1])
        if change is None: return solved[0], tuple(active), tuple(rows[i][0] for i in active), solved[1], solved[2]
        active = _apply_active_change(active, change)
    return solved[0], tuple(active), tuple(rows[i][0] for i in active), solved[1], solved[2]


def _equality_solution(base, response, rows, active, current):
    if not active: return base, np.empty(0), 0.0
    jacobian = np.asarray([rows[index][1] for index in active]); gaps = _linear_current(rows, active)
    selected = response[:, active]; schur = jacobian @ selected
    target = jacobian @ current - gaps
    multipliers = np.linalg.lstsq(schur, target - jacobian @ base, rcond=1.0e-10)[0]
    return base + selected @ multipliers, multipliers, float(np.linalg.cond(schur))


def _linear_current(rows, active):
    return np.asarray([rows[index][2] for index in active], dtype=np.float64)


def _active_change(rows, active, solved, current, multipliers):
    negative = [(value, index) for value, index in zip(multipliers, active) if value < -1.0e-10]
    if negative: return "DROP", min(negative)[1]
    inactive = [index for index in range(len(rows)) if index not in active]
    violations = [(rows[index][2] + rows[index][1] @ (solved - current), index) for index in inactive]
    if violations and min(violations)[0] < -1.0e-10: return "ADD", min(violations)[1]
    return None


def _apply_active_change(active, change):
    mode, index = change; output = list(active)
    if mode == "DROP": output.remove(index)
    elif index not in output: output.append(index)
    return sorted(output)


def _trust_limited(points, candidate, pins, radius):
    delta = candidate - points
    maximum = max((float(value) for value in np.linalg.norm(delta, axis=1)), default=0.0)
    fraction = min(1.0, float(radius) / max(maximum, np.finfo(float).eps))
    output = points + fraction * delta
    for index, target in pins.items(): output[index] = target
    return np.ascontiguousarray(output)


def _step_components(points, candidate, rows, active):
    normal, tangent = _step_vectors(points, candidate, rows, active)
    return float(np.linalg.norm(normal)), float(np.linalg.norm(tangent))


def _step_vectors(points, candidate, rows, active):
    step = (candidate - points).reshape(-1)
    if not active: return np.zeros_like(step), step
    jacobian = np.asarray([rows[index][1] for index in active])
    normal = jacobian.T @ np.linalg.lstsq(jacobian @ jacobian.T, jacobian @ step, rcond=1.0e-10)[0]
    return normal, step - normal


def _linearized_violation(points, candidate, rows):
    if not rows: return 0.0
    delta = (candidate - points).reshape(-1)
    values = [max(0.0, -(row[2] + row[1] @ delta)) for row in rows]
    return max(values, default=0.0)


def _contact_merit(rows, source, candidate):
    if not rows: return 0.0
    delta = (candidate - source).reshape(-1)
    values = [max(0.0, -(row[2] + row[1] @ delta)) for row in rows]
    return max(values, default=0.0) + float(np.linalg.norm(values))


def _feasibility_merit(metrics):
    return float(metrics.maximum_violation + np.sqrt(metrics.squared_violation))
