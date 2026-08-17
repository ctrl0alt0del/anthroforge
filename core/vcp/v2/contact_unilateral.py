"""Package 8.2 unilateral contact solve in the structural metric."""

from dataclasses import dataclass

import numpy as np

from . import structural as base


V2_UNILATERAL_CONTACT_VERSION = "fiber-v2-unilateral-contact-1"


@dataclass(frozen=True)
class UnilateralConstraint:
    nodes: tuple
    weights: tuple
    normal: tuple
    offset: float
    tag: str = ""


@dataclass(frozen=True)
class UnilateralContactResult:
    points: np.ndarray
    multipliers: np.ndarray
    gaps: np.ndarray
    active_indices: tuple
    primal_residual: float
    dual_residual: float
    stationarity_residual: float
    complementarity_residual: float
    factor_cache_hit: bool
    iterations: int
    feasible: bool
    engine_version: str = V2_UNILATERAL_CONTACT_VERSION


def solve_unilateral_contact(reference, constraints, pins=None, settings=None, cache=None,
                             tolerance=1.0e-9, active_hint=()):
    config = base._v2_settings(settings); points = base._validated_points(reference)
    fixed, targets = base._pin_data(pins, len(points)); rows = _constraints(constraints, len(points))
    store = base.DEFAULT_FACTOR_CACHE if cache is None else cache
    unconstrained, factor, hit = _base_solution(points, fixed, targets, config, store)
    matrix, offsets = _matrix(rows, len(points)); tol = _tolerance(tolerance)
    return _solve_contact(unconstrained, factor, matrix, offsets, fixed, points, config, hit, tol, active_hint)


def _constraints(constraints, count):
    return tuple(_constraint(value, count) for value in constraints)


def _constraint(value, count):
    if not isinstance(value, UnilateralConstraint):
        raise ValueError("constraints must use UnilateralConstraint")
    nodes, weights = tuple(value.nodes), np.asarray(value.weights, dtype=np.float64)
    normal = np.asarray(value.normal, dtype=np.float64); _validate_row(nodes, weights, normal, value.offset, count)
    length = float(np.linalg.norm(normal)); return UnilateralConstraint(
        tuple(int(node) for node in nodes), tuple(weights), tuple(normal / length), float(value.offset) / length, str(value.tag))


def _validate_row(nodes, weights, normal, offset, count):
    if not nodes or len(nodes) != len(weights) or any(not isinstance(node, (int, np.integer)) for node in nodes):
        raise ValueError("constraint nodes and weights must be nonempty and aligned")
    if any(int(node) < 0 or int(node) >= count for node in nodes):
        raise ValueError("constraint node is out of range")
    if normal.shape != (3,) or not np.isfinite(normal).all() or np.linalg.norm(normal) <= 0.0:
        raise ValueError("constraint normal must be a finite nonzero vector")
    if not np.isfinite(weights).all() or not np.isfinite(offset):
        raise ValueError("constraint weights and offset must be finite")


def _base_solution(reference, pinned, targets, config, cache):
    settings = base._static_settings(config); points = reference.copy(); points[pinned] = targets
    if len(pinned) == len(points):
        return points, None, False
    key = base.factor_key(len(points), pinned, settings)
    factor, hit = cache.get_or_build(key, lambda: base._build_factor(key))
    rhs = settings.rho * reference[factor.free] - base._coupling_product(factor, targets)
    rhs -= base._update_pin_product(factor, targets); points[factor.free] = base._solve_factor(factor, rhs)
    points[pinned] = targets; return points, factor, hit


def _matrix(rows, count):
    matrix = np.zeros((len(rows), count, 3), dtype=np.float64)
    for index, row in enumerate(rows):
        for node, weight in zip(row.nodes, row.weights):
            matrix[index, node] += float(weight) * np.asarray(row.normal)
    return matrix, np.asarray([row.offset for row in rows], dtype=np.float64)


def _tolerance(value):
    result = float(value)
    if not np.isfinite(result) or result <= 0.0:
        raise ValueError("unilateral tolerance must be finite and positive")
    return result


def _solve_contact(unconstrained, factor, matrix, offsets, pinned, reference, config, hit, tol, hint):
    if not len(matrix) or factor is None:
        return _terminal_result(unconstrained, matrix, offsets, pinned, reference, config, hit, 0, tol)
    free_rows = matrix[:, factor.free]; responsive = np.linalg.norm(free_rows, axis=(1, 2)) > tol
    violation = offsets - np.einsum("kni,ni->k", matrix, unconstrained)
    if np.any((~responsive) & (violation > tol)):
        return _terminal_result(unconstrained, matrix, offsets, pinned, reference, config, hit, 0, tol)
    return _responsive_result(unconstrained, factor, matrix, offsets, responsive, pinned, reference, config, hit, tol, hint)


def _responsive_result(unconstrained, factor, matrix, offsets, responsive, pinned, reference, config, hit, tol, hint):
    selected = np.flatnonzero(responsive); rows = matrix[selected][:, factor.free]
    violation = offsets[selected] - np.einsum("kni,ni->k", matrix[selected], unconstrained)
    local_hint = _local_hint(selected, hint)
    multipliers, active, iterations, influence = _metric_active_set(factor, rows, violation, tol, local_hint)
    points = _corrected(unconstrained, factor.free, influence, multipliers[np.asarray(active, dtype=np.int64)])
    full = np.zeros(len(matrix)); full[selected] = multipliers
    return _result(points, full, matrix, offsets, active, selected, pinned, reference, config, hit, iterations, tol)


def _influence(factor, rows):
    count, contacts = len(factor.free), len(rows)
    packed = rows.transpose(1, 0, 2).reshape((count, contacts * 3))
    return base._solve_factor(factor, packed).reshape((count, contacts, 3))


def _local_hint(selected, hint):
    lookup = {int(value): index for index, value in enumerate(selected)}
    return tuple(lookup[int(value)] for value in hint if int(value) in lookup)


def _metric_active_set(factor, rows, violation, tol, hint=()):
    active, seen = list(dict.fromkeys(int(value) for value in hint)), set(); multipliers = np.zeros(len(violation))
    influence = np.empty((len(factor.free), 0, 3)); limit = max(16, 4 * len(violation) + 8); restarted = False
    for iteration in range(1, limit + 1):
        key = tuple(active)
        if key in seen:
            if hint and not restarted:
                active, seen, restarted = [], set(), True; continue
            multipliers, _action, influence = _metric_trial(factor, rows, violation, active, tol)
            return multipliers, tuple(active), iteration, influence
        seen.add(key); multipliers, action, influence = _metric_trial(factor, rows, violation, active, tol)
        if action is None:
            return multipliers, tuple(active), iteration, influence
        active = action
    return multipliers, tuple(active), limit, influence


def _metric_trial(factor, rows, violation, active, tol):
    multipliers = np.zeros(len(violation)); indices = np.asarray(active, dtype=np.int64)
    influence = _influence(factor, rows[indices]); coupling = np.einsum("kfi,fai->ka", rows, influence)
    if len(indices):
        values = _solve_block(coupling[indices], violation[indices])
        if float(np.min(values)) < -tol:
            position = int(np.argmin(values)); return multipliers, active[:position] + active[position + 1:], influence
        multipliers[indices] = values
    residual = violation - coupling @ multipliers[indices]; inactive = np.ones(len(residual), dtype=bool); inactive[indices] = False
    candidate = int(np.argmax(np.where(inactive, residual, -np.inf))) if np.any(inactive) else -1
    if candidate < 0 or residual[candidate] <= tol:
        return multipliers, None, influence
    return multipliers, active + [candidate], influence


def _solve_block(matrix, rhs):
    try:
        return np.linalg.solve(matrix, rhs)
    except np.linalg.LinAlgError:
        return np.linalg.lstsq(matrix, rhs, rcond=1.0e-11)[0]


def _corrected(unconstrained, free, influence, multipliers):
    points = unconstrained.copy(); points[free] += np.einsum("fki,k->fi", influence, multipliers)
    return points


def _result(points, multipliers, matrix, offsets, active, selected, pinned, reference, config, hit, iterations, tol):
    mapped = tuple(int(selected[index]) for index in active)
    return _contact_result(points, multipliers, matrix, offsets, mapped, pinned, reference, config, hit, iterations, tol)


def _terminal_result(points, matrix, offsets, pinned, reference, config, hit, iterations, tol):
    multipliers = np.zeros(len(matrix)); active = ()
    return _contact_result(points, multipliers, matrix, offsets, active, pinned, reference, config, hit, iterations, tol)


def _contact_result(points, multipliers, matrix, offsets, active, pinned, reference, config, hit, iterations, tol):
    gaps = np.einsum("kni,ni->k", matrix, points) - offsets
    primal = max(0.0, float(-np.min(gaps))) if len(gaps) else 0.0
    dual = max(0.0, float(-np.min(multipliers))) if len(multipliers) else 0.0
    stationarity = _stationarity(points, multipliers, matrix, pinned, reference, config)
    complementarity = float(np.max(np.abs(multipliers * gaps))) if len(gaps) else 0.0
    arrays = tuple(_readonly(value) for value in (points, multipliers, gaps))
    return UnilateralContactResult(*arrays, tuple(active), primal, dual, stationarity,
                                    complementarity, bool(hit), int(iterations), primal <= tol and dual <= tol)


def _stationarity(points, multipliers, matrix, pinned, reference, config):
    gradient = base._normal_gradient(points, reference, base._static_settings(config))
    gradient -= np.einsum("kni,k->ni", matrix, multipliers)
    mask = np.ones(len(points), dtype=bool); mask[pinned] = False; values = gradient[mask]
    return float(np.max(np.linalg.norm(values, axis=1))) if len(values) else 0.0


def _readonly(value):
    output = np.ascontiguousarray(value); output.setflags(write=False); return output
