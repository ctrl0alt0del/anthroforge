"""Experimental active-set trust-region step for the Fiber V2 contact core."""

from dataclasses import dataclass
from time import perf_counter

import numpy as np

from .collision_native import native_structural_contact_responses
from .structural import _base_bands, _static_settings, structural_energy


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
    variant: str = "BASE"
    normal_fraction: float = 1.0
    tangential_fraction: float = 1.0
    soc_norm: float = 0.0


def solve_trust_sqp(points, reference, settings, contacts, pins, trust_radius):
    started = perf_counter(); rows = _linear_contacts(points, contacts)
    problem = _native_problem(reference, settings, contacts, pins)
    solved = _active_set(problem[0], problem[1], rows, np.asarray(points).reshape(-1))
    candidate = solved[0].reshape((-1, 3))
    candidate = _trust_limited(points, candidate, pins, trust_radius)
    normal, tangent = _step_components(points, candidate, rows, solved[1])
    violation = _linearized_violation(points, candidate, rows)
    energy = structural_energy(candidate, reference, settings).total
    elapsed = 1000.0 * (perf_counter() - started)
    return V2TrustSqpStep(candidate, solved[2], tuple(solved[3]), violation, energy,
                          normal, tangent, elapsed, max(problem[2]["condition"], solved[4]))


def solve_composite_sqp(points, reference, settings, contacts, pins, trust_radius, variant):
    started = perf_counter(); rows = _linear_contacts(points, contacts)
    problem = _native_problem(reference, settings, contacts, pins)
    solved = _active_set(problem[0], problem[1], rows, np.asarray(points).reshape(-1))
    normal, tangent = _step_vectors(points, solved[0].reshape((-1, 3)), rows, solved[1])
    delta, fractions = _composite_delta(normal, tangent, len(points), trust_radius, variant)
    candidate = _pinned_candidate(points, delta, pins)
    violation = _linearized_violation(points, candidate, rows)
    energy = structural_energy(candidate, reference, settings).total
    elapsed = 1000.0 * (perf_counter() - started)
    return V2TrustSqpStep(candidate, solved[2], tuple(solved[3]), violation, energy,
        float(np.linalg.norm(normal)), float(np.linalg.norm(tangent)), elapsed,
        max(problem[2]["condition"], solved[4]), variant, *fractions)


def second_order_correction(candidate, contacts, pins, trust_radius):
    rows = tuple(row for row in contacts if row.gap < 0.0)
    if not rows: return np.ascontiguousarray(candidate), 0.0, 0.0
    jacobian = np.asarray([_contact_jacobian(len(candidate), row) for row in rows])
    jacobian = _free_jacobian(jacobian, pins); target = -np.asarray([row.gap for row in rows])
    schur = jacobian @ jacobian.T; regularized = _regularized(schur)
    correction = jacobian.T @ np.linalg.lstsq(regularized, target, rcond=1.0e-10)[0]
    correction = _limit_flat(correction, len(candidate), .5 * trust_radius)[0]
    output = _pinned_candidate(candidate, correction, pins)
    return output, float(np.linalg.norm(correction)), float(np.linalg.cond(regularized))


def update_trust_radius(radius, minimum, maximum, ratio, accepted, boundary, contact_changed=False):
    if contact_changed: return max(minimum, min(maximum, radius))
    if not accepted or not np.isfinite(ratio) or ratio < .1: return max(minimum, .25 * radius)
    if ratio < .25: return max(minimum, .5 * radius)
    if ratio > .75 and boundary: return min(maximum, 2.0 * radius)
    return max(minimum, min(maximum, radius))


def model_reduction(points, candidate, reference, settings, contacts, pins, feasible):
    if feasible:
        before = structural_energy(points, reference, settings).total
        return before - structural_energy(candidate, reference, settings).total
    rows = _linear_contacts(points, contacts)
    return _contact_merit(rows, points, points) - _contact_merit(rows, points, candidate)


def actual_reduction(before, after, energy_before, energy_after, feasible):
    if feasible: return float(energy_before - energy_after)
    return _feasibility_merit(before) - _feasibility_merit(after)


def _native_problem(reference, settings, contacts, pins):
    count = len(reference); bands = _base_bands(count, _static_settings(settings))
    rhs = settings.fidelity_weight * np.asarray(reference, dtype=np.float64)
    rows = tuple((row.edge, row.factor, row.normal) for row in contacts)
    indices = tuple(sorted(pins)); targets = tuple(pins[index] for index in indices)
    return native_structural_contact_responses(bands, rhs, rows, indices, targets)


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


def _composite_delta(normal, tangent, count, radius, variant):
    if variant == "TANGENTIAL":
        limited, fraction = _limit_flat(tangent, count, radius)
        return limited, (0.0, fraction)
    limited, normal_fraction = _limit_flat(normal, count, radius)
    tangent_fraction = _tangent_fraction(limited, tangent, count, radius)
    return limited + tangent_fraction * tangent, (normal_fraction, tangent_fraction)


def _limit_flat(values, count, radius):
    rows = np.asarray(values, dtype=np.float64).reshape((count, 3))
    maximum = max((float(value) for value in np.linalg.norm(rows, axis=1)), default=0.0)
    fraction = min(1.0, float(radius) / max(maximum, np.finfo(float).eps))
    return fraction * rows.reshape(-1), fraction


def _tangent_fraction(normal, tangent, count, radius):
    if not np.any(tangent): return 0.0
    low, high = 0.0, 1.0
    for _iteration in range(24):
        middle = .5 * (low + high)
        if _within_radius(normal + middle * tangent, count, radius): low = middle
        else: high = middle
    return low


def _within_radius(values, count, radius):
    rows = np.asarray(values).reshape((count, 3))
    maximum = max((float(value) for value in np.linalg.norm(rows, axis=1)), default=0.0)
    return maximum <= float(radius) * (1.0 + 1.0e-12)


def _pinned_candidate(points, delta, pins):
    output = np.asarray(points, dtype=np.float64) + np.asarray(delta).reshape((-1, 3))
    for index, target in pins.items(): output[index] = target
    return np.ascontiguousarray(output)


def _free_jacobian(jacobian, pins):
    output = np.asarray(jacobian, dtype=np.float64).copy()
    for index in pins: output[:, 3 * index:3 * index + 3] = 0.0
    return output


def _regularized(matrix):
    scale = max(1.0, float(np.linalg.norm(matrix, ord=np.inf)))
    return matrix + (1.0e-10 * scale) * np.eye(len(matrix))


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
