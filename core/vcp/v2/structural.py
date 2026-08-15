"""Blender-independent static Fiber V2 structural objective.

The solved quadratic is ``rho*||x-q||^2 + (wL/h)*||D1*x||^2 +
(wB/h^3)*||D2*x||^2``. Pins are eliminated from the linear system.
"""

from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

from .contracts import V2Settings, V2Topology


OPEN = "OPEN"
CYCLIC = "CYCLIC"
_DEFAULT_CACHE_BYTES = 64 * 1024 * 1024
V2_STRUCTURAL_VERSION = "fiber-v2-structural-1"


@dataclass(frozen=True)
class StaticFiberSettings:
    length_weight: float = 0.1
    bend_weight: float = 0.001
    rho: float = 1.0
    topology: str = OPEN


@dataclass(frozen=True)
class StaticFiberEnergy:
    fidelity: float
    length: float
    bend: float

    @property
    def total(self):
        return self.fidelity + self.length + self.bend


@dataclass(frozen=True)
class StaticFiberResult:
    points: np.ndarray
    energy: StaticFiberEnergy
    stationarity_residual: float
    factor_cache_hit: bool


@dataclass(frozen=True)
class FiberFactorKey:
    count: int
    topology: str
    free_mask: tuple
    length_weight: float
    bend_weight: float
    rho: float


@dataclass(frozen=True)
class _ReducedFactor:
    free: np.ndarray
    pinned: np.ndarray
    diagonal: np.ndarray
    lower1: np.ndarray
    lower2: np.ndarray
    coupling_rows: np.ndarray
    coupling_cols: np.ndarray
    coupling_values: np.ndarray
    update_free: np.ndarray
    update_pinned: np.ndarray
    woodbury_basis: np.ndarray
    woodbury_lower: np.ndarray

    @property
    def nbytes(self):
        arrays = tuple(value for value in vars(self).values() if isinstance(value, np.ndarray))
        return sum(value.nbytes for value in arrays)


class FiberFactorCache:
    def __init__(self, max_entries=16, max_bytes=_DEFAULT_CACHE_BYTES):
        if int(max_entries) < 1 or int(max_bytes) < 1:
            raise ValueError("factor cache limits must be positive")
        self.max_entries, self.max_bytes = int(max_entries), int(max_bytes)
        self._entries, self._bytes = OrderedDict(), 0
        self.hits = self.misses = self.factor_builds = self.evictions = 0

    def get_or_build(self, key, builder):
        found = self._entries.get(key)
        if found is not None:
            self.hits += 1
            self._entries.move_to_end(key)
            return found, True
        self.misses += 1
        value = builder()
        self.factor_builds += 1
        self._store(key, value)
        return value, False

    def _store(self, key, value):
        if value.nbytes > self.max_bytes:
            return
        self._entries[key] = value
        self._bytes += value.nbytes
        self._evict_excess()

    def _evict_excess(self):
        while len(self._entries) > self.max_entries or self._bytes > self.max_bytes:
            _key, value = self._entries.popitem(last=False)
            self._bytes -= value.nbytes
            self.evictions += 1

    def clear(self):
        self._entries.clear()
        self._bytes = 0
        self.hits = self.misses = self.factor_builds = self.evictions = 0

    def stats(self):
        return {"entries": len(self._entries), "bytes": self._bytes,
                "hits": self.hits, "misses": self.misses,
                "factor_builds": self.factor_builds, "evictions": self.evictions}


DEFAULT_FACTOR_CACHE = FiberFactorCache()


def clear_factor_cache():
    DEFAULT_FACTOR_CACHE.clear()


def factor_cache_stats():
    return DEFAULT_FACTOR_CACHE.stats()


def solve_static_fiber(seed, pin_targets=None, settings=None, factor_cache=None):
    settings = settings or StaticFiberSettings()
    points = _validated_points(seed)
    _validate_settings(settings, len(points))
    pinned, targets = _pin_data(pin_targets, len(points))
    cache = DEFAULT_FACTOR_CACHE if factor_cache is None else factor_cache
    solved, hit = _solve_reduced(points, pinned, targets, settings, cache)
    energy = static_fiber_energy(solved, points, settings)
    residual = _stationarity_residual(solved, points, pinned, settings)
    return StaticFiberResult(solved, energy, residual, hit)


def static_fiber_energy(points, seed, settings=None):
    settings = settings or StaticFiberSettings()
    values, reference = _validated_pair(points, seed)
    _validate_settings(settings, len(values))
    _h, length_scale, bend_scale = smooth_coefficients(len(values), settings)
    fidelity = settings.rho * float(np.sum((values - reference) ** 2))
    length = length_scale * float(np.sum(_first_values(values, settings) ** 2))
    bend = bend_scale * float(np.sum(_second_values(values, settings) ** 2))
    return StaticFiberEnergy(fidelity, length, bend)


def smooth_coefficients(count, settings=None):
    settings = settings or StaticFiberSettings()
    _validate_settings(settings, int(count))
    h = 1.0 / (int(count) if settings.topology == CYCLIC else int(count) - 1)
    return h, settings.length_weight / h, settings.bend_weight / (h ** 3)


def assemble_normal_matrix(count, settings=None):
    settings = settings or StaticFiberSettings()
    _h, length_scale, bend_scale = smooth_coefficients(count, settings)
    matrix = np.eye(int(count), dtype=np.float64) * settings.rho
    _add_gram_rows(matrix, _first_rows(int(count), settings.topology), length_scale)
    _add_gram_rows(matrix, _second_rows(int(count), settings.topology), bend_scale)
    return matrix


def factor_key(count, pinned, settings=None):
    settings = settings or StaticFiberSettings()
    _validate_settings(settings, int(count))
    mask = np.ones(int(count), dtype=bool)
    mask[_validated_pin_indices(pinned, count)] = False
    return FiberFactorKey(int(count), settings.topology, tuple(bool(v) for v in mask),
                          float(settings.length_weight), float(settings.bend_weight),
                          float(settings.rho))


def _validated_points(points):
    values = np.asarray(points, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError("Fiber points must have shape (N, 3)")
    if not np.isfinite(values).all():
        raise ValueError("Fiber points must be finite")
    return np.ascontiguousarray(values)


def _validated_pair(points, seed):
    values, reference = _validated_points(points), _validated_points(seed)
    if values.shape != reference.shape:
        raise ValueError("Fiber points and seed must have matching shapes")
    return values, reference


def _validate_settings(settings, count):
    weights = settings.length_weight, settings.bend_weight, settings.rho
    if settings.topology not in (OPEN, CYCLIC):
        raise ValueError("Fiber topology must be OPEN or CYCLIC")
    if int(count) < (3 if settings.topology == CYCLIC else 2):
        raise ValueError("Fiber topology has too few points")
    if not all(np.isfinite(value) for value in weights):
        raise ValueError("Fiber solver weights must be finite")
    if settings.length_weight < 0.0 or settings.bend_weight < 0.0 or settings.rho <= 0.0:
        raise ValueError("Fiber weights must be nonnegative and rho must be positive")


def _pin_data(pin_targets, count):
    items = () if pin_targets is None else tuple(pin_targets.items())
    if any(not isinstance(index, (int, np.integer)) for index, _target in items):
        raise ValueError("Fiber pin indices must be integers")
    rows = sorted((int(index), np.asarray(target, dtype=np.float64)) for index, target in items)
    _validate_pin_rows(rows, count)
    indices = np.asarray([index for index, _target in rows], dtype=np.int64)
    targets = np.asarray([target for _index, target in rows], dtype=np.float64).reshape((-1, 3))
    return indices, targets


def _validate_pin_rows(rows, count):
    if any(index < 0 or index >= int(count) for index, _target in rows):
        raise ValueError("Fiber pin index is out of range")
    if any(target.shape != (3,) for _index, target in rows):
        raise ValueError("Fiber pin targets must have shape (3,)")
    if any(not np.isfinite(target).all() for _index, target in rows):
        raise ValueError("Fiber pin targets must be finite")


def _validated_pin_indices(pinned, count):
    values = tuple(pinned)
    if any(not isinstance(index, (int, np.integer)) for index in values):
        raise ValueError("Fiber pin indices must be integers")
    indices = np.asarray(values, dtype=np.int64)
    if np.any(indices < 0) or np.any(indices >= int(count)):
        raise ValueError("Fiber pin index is out of range")
    return indices


def _solve_reduced(seed, pinned, targets, settings, cache):
    points = seed.copy()
    points[pinned] = targets
    if len(pinned) == len(seed):
        return points, False
    key = factor_key(len(seed), pinned, settings)
    factor, hit = cache.get_or_build(key, lambda: _build_factor(key))
    rhs = settings.rho * seed[factor.free] - _coupling_product(factor, targets)
    rhs -= _update_pin_product(factor, targets)
    points[factor.free] = _solve_factor(factor, rhs)
    points[pinned] = targets
    return points, hit


def _build_factor(key):
    settings = StaticFiberSettings(key.length_weight, key.bend_weight, key.rho, key.topology)
    free = np.flatnonzero(np.asarray(key.free_mask, dtype=bool))
    pinned = np.flatnonzero(~np.asarray(key.free_mask, dtype=bool))
    bands = _base_bands(key.count, settings)
    diagonal, lower1, lower2 = _reduced_bands(bands, free)
    factors = _factor_pentadiagonal(diagonal, lower1, lower2)
    coupling = _base_coupling(bands, free, pinned)
    updates = _reduced_updates(key.count, settings, free, pinned)
    woodbury = _woodbury_data(factors, updates[0])
    values = (free, pinned, *factors, *coupling, *updates, *woodbury)
    return _ReducedFactor(*(_readonly(value) for value in values))


def _readonly(value):
    out = np.ascontiguousarray(value)
    out.setflags(write=False)
    return out


def _base_bands(count, settings):
    _h, length_scale, bend_scale = smooth_coefficients(count, settings)
    diagonal = np.full(count, settings.rho, dtype=np.float64)
    lower1 = np.zeros(count, dtype=np.float64)
    lower2 = np.zeros(count, dtype=np.float64)
    _add_first_bands(diagonal, lower1, length_scale)
    _add_second_bands(diagonal, lower1, lower2, bend_scale)
    return diagonal, lower1, lower2


def _add_first_bands(diagonal, lower1, scale):
    diagonal[:-1] += scale
    diagonal[1:] += scale
    lower1[1:] -= scale


def _add_second_bands(diagonal, lower1, lower2, scale):
    if len(diagonal) < 3:
        return
    diagonal[:-2] += scale
    diagonal[1:-1] += 4.0 * scale
    diagonal[2:] += scale
    lower1[1:-1] -= 2.0 * scale
    lower1[2:] -= 2.0 * scale
    lower2[2:] += scale


def _reduced_bands(bands, free):
    diagonal, lower1, lower2 = bands
    reduced1 = np.zeros(len(free), dtype=np.float64)
    reduced2 = np.zeros(len(free), dtype=np.float64)
    if len(free) > 1:
        gaps = free[1:] - free[:-1]
        reduced1[1:] = _gather_band(lower1, lower2, free[1:], gaps)
    if len(free) > 2:
        gaps = free[2:] - free[:-2]
        reduced2[2:] = np.where(gaps == 2, lower2[free[2:]], 0.0)
    return diagonal[free].copy(), reduced1, reduced2


def _gather_band(lower1, lower2, rows, gaps):
    return np.where(gaps == 1, lower1[rows], np.where(gaps == 2, lower2[rows], 0.0))


def _factor_pentadiagonal(diagonal, lower1, lower2):
    pivots = np.empty_like(diagonal)
    factor1, factor2 = np.zeros_like(lower1), np.zeros_like(lower2)
    for row in range(len(diagonal)):
        if row > 1:
            factor2[row] = lower2[row] / pivots[row - 2]
        if row:
            cross = factor2[row] * pivots[row - 2] * factor1[row - 1] if row > 1 else 0.0
            factor1[row] = (lower1[row] - cross) / pivots[row - 1]
        pivot = diagonal[row] - _pivot_correction(row, pivots, factor1, factor2)
        if not np.isfinite(pivot) or pivot <= 0.0:
            raise np.linalg.LinAlgError("Fiber band factor is not positive definite")
        pivots[row] = pivot
    return pivots, factor1, factor2


def _pivot_correction(row, pivots, lower1, lower2):
    first = lower1[row] ** 2 * pivots[row - 1] if row else 0.0
    second = lower2[row] ** 2 * pivots[row - 2] if row > 1 else 0.0
    return first + second


def _base_coupling(bands, free, pinned):
    pin_map = np.full(len(bands[0]), -1, dtype=np.int64)
    pin_map[pinned] = np.arange(len(pinned), dtype=np.int64)
    entries = _coupling_entries(bands, free, pin_map)
    if not entries:
        empty_i = np.empty(0, dtype=np.int64)
        return empty_i, empty_i.copy(), np.empty(0, dtype=np.float64)
    rows, columns, values = zip(*entries)
    return np.asarray(rows), np.asarray(columns), np.asarray(values)


def _coupling_entries(bands, free, pin_map):
    entries = []
    for row, node in enumerate(free):
        start, stop = max(0, node - 2), min(len(pin_map), node + 3)
        for other in range(start, stop):
            column = pin_map[other]
            value = _band_value(bands, node, other)
            if column >= 0 and value != 0.0:
                entries.append((row, column, value))
    return entries


def _band_value(bands, row, column):
    diagonal, lower1, lower2 = bands
    distance, high = abs(row - column), max(row, column)
    if distance == 0:
        return diagonal[row]
    if distance == 1:
        return lower1[high]
    return lower2[high] if distance == 2 else 0.0


def _cyclic_updates(count, settings):
    if settings.topology != CYCLIC:
        return np.empty((count, 0), dtype=np.float64)
    _h, length_scale, bend_scale = smooth_coefficients(count, settings)
    columns = []
    if length_scale:
        columns.append(_sparse_column(count, (count - 1, 0), (-1.0, 1.0), length_scale))
    if bend_scale:
        columns += _cyclic_bend_columns(count, bend_scale)
    return np.column_stack(columns) if columns else np.empty((count, 0), dtype=np.float64)


def _cyclic_bend_columns(count, scale):
    first = _sparse_column(count, (count - 1, 0, 1), (1.0, -2.0, 1.0), scale)
    last = _sparse_column(count, (count - 2, count - 1, 0), (1.0, -2.0, 1.0), scale)
    return [first, last]


def _sparse_column(count, indices, values, scale):
    column = np.zeros(count, dtype=np.float64)
    np.add.at(column, np.asarray(indices), np.sqrt(scale) * np.asarray(values))
    return column


def _reduced_updates(count, settings, free, pinned):
    updates = _cyclic_updates(count, settings)
    return updates[free].copy(), updates[pinned].copy()


def _woodbury_data(factors, update_free):
    if not update_free.shape[1]:
        return np.empty_like(update_free), np.empty((0, 0), dtype=np.float64)
    basis = _solve_ldlt(*factors, update_free)
    correction = np.eye(update_free.shape[1]) + update_free.T @ basis
    return basis, np.linalg.cholesky(correction)


def _coupling_product(factor, targets):
    result = np.zeros((len(factor.free), 3), dtype=np.float64)
    if len(factor.coupling_values):
        values = factor.coupling_values[:, None] * targets[factor.coupling_cols]
        np.add.at(result, factor.coupling_rows, values)
    return result


def _update_pin_product(factor, targets):
    if not factor.update_free.shape[1]:
        return np.zeros((len(factor.free), 3), dtype=np.float64)
    return factor.update_free @ (factor.update_pinned.T @ targets)


def _solve_ldlt(diagonal, lower1, lower2, rhs):
    forward = _band_forward(lower1, lower2, rhs)
    scaled = forward / diagonal[:, None]
    return _band_backward(lower1, lower2, scaled)


def _band_forward(lower1, lower2, rhs):
    solved = np.empty_like(rhs)
    for row in range(len(rhs)):
        solved[row] = rhs[row]
        if row:
            solved[row] -= lower1[row] * solved[row - 1]
        if row > 1:
            solved[row] -= lower2[row] * solved[row - 2]
    return solved


def _band_backward(lower1, lower2, rhs):
    solved = np.empty_like(rhs)
    for row in range(len(rhs) - 1, -1, -1):
        solved[row] = rhs[row]
        if row + 1 < len(rhs):
            solved[row] -= lower1[row + 1] * solved[row + 1]
        if row + 2 < len(rhs):
            solved[row] -= lower2[row + 2] * solved[row + 2]
    return solved


def _solve_factor(factor, rhs):
    solved = _solve_ldlt(factor.diagonal, factor.lower1, factor.lower2, rhs)
    if not factor.update_free.shape[1]:
        return solved
    projected = factor.update_free.T @ solved
    weights = _solve_cholesky(factor.woodbury_lower, projected)
    return solved - factor.woodbury_basis @ weights


def _solve_cholesky(lower, rhs):
    return _dense_back_substitute(lower, _dense_forward_substitute(lower, rhs))


def _dense_forward_substitute(lower, rhs):
    solved = np.empty_like(rhs)
    for row in range(len(lower)):
        prior = lower[row, :row] @ solved[:row]
        solved[row] = (rhs[row] - prior) / lower[row, row]
    return solved


def _dense_back_substitute(lower, rhs):
    solved = np.empty_like(rhs)
    for row in range(len(lower) - 1, -1, -1):
        prior = lower[row + 1:, row] @ solved[row + 1:]
        solved[row] = (rhs[row] - prior) / lower[row, row]
    return solved


def _first_rows(count, topology):
    size = count if topology == CYCLIC else count - 1
    return (((index, (index + 1) % count), (-1.0, 1.0)) for index in range(size))


def _second_rows(count, topology):
    if topology == CYCLIC:
        return ((((index - 1) % count, index, (index + 1) % count),
                 (1.0, -2.0, 1.0)) for index in range(count))
    return (((index, index + 1, index + 2), (1.0, -2.0, 1.0))
            for index in range(count - 2))


def _add_gram_rows(matrix, rows, scale):
    if scale == 0.0:
        return
    for indices, values in rows:
        block = np.ix_(indices, indices)
        matrix[block] += float(scale) * np.outer(values, values)


def _first_values(points, settings):
    if settings.topology == CYCLIC:
        return np.roll(points, -1, axis=0) - points
    return np.diff(points, axis=0)


def _second_values(points, settings):
    if settings.topology == CYCLIC:
        return np.roll(points, 1, axis=0) - 2.0 * points + np.roll(points, -1, axis=0)
    return points[:-2] - 2.0 * points[1:-1] + points[2:]


def _normal_gradient(points, seed, settings):
    _h, length_scale, bend_scale = smooth_coefficients(len(points), settings)
    gradient = settings.rho * (points - seed)
    _add_first_adjoint(gradient, _first_values(points, settings), length_scale, settings)
    _add_second_adjoint(gradient, _second_values(points, settings), bend_scale, settings)
    return gradient


def _add_first_adjoint(gradient, values, scale, settings):
    if settings.topology == CYCLIC:
        gradient += scale * (np.roll(values, 1, axis=0) - values)
        return
    gradient[:-1] -= scale * values
    gradient[1:] += scale * values


def _add_second_adjoint(gradient, values, scale, settings):
    if settings.topology == CYCLIC:
        gradient += scale * (np.roll(values, 1, axis=0) - 2.0 * values + np.roll(values, -1, axis=0))
        return
    gradient[:-2] += scale * values
    gradient[1:-1] -= 2.0 * scale * values
    gradient[2:] += scale * values


def _stationarity_residual(points, seed, pinned, settings):
    free = np.ones(len(points), dtype=bool)
    free[pinned] = False
    if not np.any(free):
        return 0.0
    residual = _normal_gradient(points, seed, settings)[free]
    return float(np.max(np.linalg.norm(residual, axis=1)))


@dataclass(frozen=True)
class V2StructuralEnergy:
    fidelity: float
    length: float
    curvature: float

    @property
    def total(self):
        return self.fidelity + self.length + self.curvature


@dataclass(frozen=True)
class V2StructuralResult:
    points: np.ndarray
    energy: V2StructuralEnergy
    stationarity_residual: float
    factor_cache_hit: bool
    engine_version: str = V2_STRUCTURAL_VERSION


def solve_structural(reference, pin_targets=None, settings=None, factor_cache=None):
    config = _v2_settings(settings)
    solved = solve_static_fiber(reference, pin_targets, _static_settings(config), factor_cache)
    points = solved.points.copy()
    points.setflags(write=False)
    energy = V2StructuralEnergy(solved.energy.fidelity, solved.energy.length, solved.energy.bend)
    return V2StructuralResult(points, energy, solved.stationarity_residual,
                              solved.factor_cache_hit)


def structural_energy(points, reference, settings=None):
    energy = static_fiber_energy(points, reference, _static_settings(_v2_settings(settings)))
    return V2StructuralEnergy(energy.fidelity, energy.length, energy.bend)


def _v2_settings(settings):
    if settings is None:
        return V2Settings()
    if not isinstance(settings, V2Settings):
        raise ValueError("settings must use the V2Settings contract")
    return settings


def _static_settings(settings):
    topology = V2Topology(settings.topology).value
    return StaticFiberSettings(settings.length_weight, settings.curvature_weight,
                               settings.fidelity_weight, topology)


StructuralFactorCache = FiberFactorCache
DEFAULT_STRUCTURAL_CACHE = DEFAULT_FACTOR_CACHE


def clear_structural_cache():
    clear_factor_cache()


def structural_cache_stats():
    return factor_cache_stats()

