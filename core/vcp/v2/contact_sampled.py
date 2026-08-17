"""O(N) structural solve with fixed quadrature contact slots per edge."""

from dataclasses import dataclass

import numpy as np

from . import structural as base
from .contact_structural import ContactSlotEnergy
from .contracts import V2Settings, V2Topology


V2_SAMPLED_CONTACT_VERSION = "fiber-v2-sampled-contact-1"
DEFAULT_SAMPLE_FACTORS = (0.1, 0.3, 0.5, 0.7, 0.9)


@dataclass(frozen=True)
class SampledContactFactorKey:
    count: int
    topology: str
    free_mask: tuple
    length_weight: float
    bend_weight: float
    rho: float
    contact_weight: float
    sample_factors: tuple


@dataclass(frozen=True)
class SampledContactResult:
    points: np.ndarray
    energy: ContactSlotEnergy
    stationarity_residual: float
    factor_cache_hit: bool
    engine_version: str = V2_SAMPLED_CONTACT_VERSION


DEFAULT_SAMPLED_CONTACT_CACHE = base.FiberFactorCache()


def solve_sampled_contact(reference, targets, pins=None, settings=None, contact_weight=10.0,
                          sample_factors=DEFAULT_SAMPLE_FACTORS, cache=None):
    config = _settings(settings); values = base._validated_points(reference)
    factors = _factors(sample_factors); slots = _targets(values, targets, factors, config)
    pinned, fixed = base._pin_data(pins, len(values)); weight = _weight(contact_weight)
    store = DEFAULT_SAMPLED_CONTACT_CACHE if cache is None else cache
    solved, hit = _solve(values, slots, pinned, fixed, config, weight, factors, store)
    energy = sampled_contact_energy(solved, values, slots, config, weight, factors)
    residual = sampled_contact_stationarity(solved, values, slots, pinned, config, weight, factors)
    return SampledContactResult(_readonly(solved), energy, residual, hit)


def sampled_contact_energy(points, reference, targets, settings=None, contact_weight=10.0,
                           sample_factors=DEFAULT_SAMPLE_FACTORS):
    config = _settings(settings); values = base._validated_points(points)
    reference = base._validated_points(reference); factors = _factors(sample_factors)
    slots = _targets(values, targets, factors, config); weight = _weight(contact_weight)
    structural = base.structural_energy(values, reference, config).total
    residual = sample_edge_points(values, factors, config) - slots
    edge = weight * float(np.sum(residual ** 2)) / len(factors)
    return ContactSlotEnergy(float(structural), 0.0, edge)


def sampled_contact_stationarity(points, reference, targets, pinned=(), settings=None,
                                 contact_weight=10.0, sample_factors=DEFAULT_SAMPLE_FACTORS):
    config = _settings(settings); values = base._validated_points(points)
    reference = base._validated_points(reference); factors = _factors(sample_factors)
    slots = _targets(values, targets, factors, config); weight = _weight(contact_weight)
    gradient = _gradient(values, reference, slots, config, weight, factors)
    mask = np.ones(len(values), dtype=bool); mask[base._validated_pin_indices(pinned, len(values))] = False
    rows = gradient[mask]
    return float(np.max(np.linalg.norm(rows, axis=1))) if len(rows) else 0.0


def assemble_sampled_contact_matrix(count, settings=None, contact_weight=10.0,
                                    sample_factors=DEFAULT_SAMPLE_FACTORS):
    config = _settings(settings); factors = _factors(sample_factors)
    matrix = base.assemble_normal_matrix(int(count), base._static_settings(config))
    _add_sample_gram(matrix, config, _weight(contact_weight), factors)
    return matrix


def sample_edge_points(points, sample_factors=DEFAULT_SAMPLE_FACTORS, settings=None):
    config = _settings(settings); values = base._validated_points(points); factors = _factors(sample_factors)
    count = len(values) if config.topology is V2Topology.CYCLIC else len(values) - 1
    starts = values[np.arange(count)]; ends = values[(np.arange(count) + 1) % len(values)]
    return starts[:, None, :] * (1.0 - factors[None, :, None]) + ends[:, None, :] * factors[None, :, None]


def clear_sampled_contact_cache():
    DEFAULT_SAMPLED_CONTACT_CACHE.clear()


def sampled_contact_cache_stats():
    return DEFAULT_SAMPLED_CONTACT_CACHE.stats()


def _settings(settings):
    if settings is None:
        return V2Settings()
    if not isinstance(settings, V2Settings):
        raise ValueError("settings must use the V2Settings contract")
    return settings


def _factors(values):
    factors = np.asarray(tuple(values), dtype=np.float64)
    if factors.ndim != 1 or not len(factors) or not np.isfinite(factors).all():
        raise ValueError("sample factors must be a finite nonempty sequence")
    if np.any(factors <= 0.0) or np.any(factors >= 1.0) or np.any(np.diff(factors) <= 0.0):
        raise ValueError("sample factors must be unique, increasing, and inside (0, 1)")
    return factors


def _weight(value):
    weight = float(value)
    if not np.isfinite(weight) or weight <= 0.0:
        raise ValueError("contact weight must be finite and positive")
    return weight


def _targets(reference, targets, factors, settings):
    values = np.ascontiguousarray(targets, dtype=np.float64)
    count = len(reference) if settings.topology is V2Topology.CYCLIC else len(reference) - 1
    if values.shape != (count, len(factors), 3) or not np.isfinite(values).all():
        raise ValueError("sample targets must match edge and factor counts")
    return values


def _solve(reference, slots, pinned, targets, settings, weight, factors, cache):
    points = reference.copy(); points[pinned] = targets
    if len(pinned) == len(reference):
        return points, False
    key = _factor_key(len(reference), pinned, settings, weight, factors)
    factor, hit = cache.get_or_build(key, lambda: _build_factor(key))
    rhs = _rhs(reference, slots, settings, weight, factors)[factor.free]
    rhs -= base._coupling_product(factor, targets) + base._update_pin_product(factor, targets)
    points[factor.free] = base._solve_factor(factor, rhs); points[pinned] = targets
    return points, hit


def _factor_key(count, pinned, settings, weight, factors):
    mask = np.ones(int(count), dtype=bool); mask[pinned] = False
    return SampledContactFactorKey(int(count), V2Topology(settings.topology).value,
                                   tuple(bool(value) for value in mask), float(settings.length_weight),
                                   float(settings.curvature_weight), float(settings.fidelity_weight),
                                   float(weight), tuple(float(value) for value in factors))


def _build_factor(key):
    settings = base.StaticFiberSettings(key.length_weight, key.bend_weight, key.rho, key.topology)
    free = np.flatnonzero(np.asarray(key.free_mask)); pinned = np.flatnonzero(~np.asarray(key.free_mask))
    bands = _sample_bands(key.count, settings, key.contact_weight, key.sample_factors)
    factors = base._factor_pentadiagonal(*base._reduced_bands(bands, free))
    coupling = base._base_coupling(bands, free, pinned)
    updates = _reduced_updates(key, settings, free, pinned)
    woodbury = base._woodbury_data(factors, updates[0]); values = (free, pinned, *factors, *coupling, *updates, *woodbury)
    return base._ReducedFactor(*(base._readonly(value) for value in values))


def _sample_bands(count, settings, weight, factors):
    diagonal, lower1, lower2 = base._base_bands(count, settings); values = np.asarray(factors)
    scale = float(weight) / len(values); first = scale * float(np.sum((1.0 - values) ** 2))
    second = scale * float(np.sum(values ** 2)); cross = scale * float(np.sum(values * (1.0 - values)))
    diagonal[:-1] += first; diagonal[1:] += second; lower1[1:] += cross
    return diagonal, lower1, lower2


def _reduced_updates(key, settings, free, pinned):
    updates = base._cyclic_updates(key.count, settings)
    contact = _cyclic_sample_updates(key.count, key.topology, key.contact_weight, key.sample_factors)
    if contact.shape[1]:
        updates = np.column_stack((updates, contact))
    return updates[free].copy(), updates[pinned].copy()


def _cyclic_sample_updates(count, topology, weight, factors):
    if topology != base.CYCLIC:
        return np.empty((count, 0), dtype=np.float64)
    values = np.asarray(factors); columns = np.zeros((count, len(values)), dtype=np.float64)
    scale = np.sqrt(float(weight) / len(values)); columns[0] = scale * values
    columns[-1] = scale * (1.0 - values); return columns


def _rhs(reference, targets, settings, weight, factors):
    rhs = float(settings.fidelity_weight) * reference; scale = float(weight) / len(factors)
    for edge, rows in enumerate(targets):
        for factor, target in zip(factors, rows):
            rhs[edge] += scale * (1.0 - factor) * target
            rhs[(edge + 1) % len(rhs)] += scale * factor * target
    return rhs


def _gradient(points, reference, targets, settings, weight, factors):
    gradient = base._normal_gradient(points, reference, base._static_settings(settings))
    residual = sample_edge_points(points, factors, settings) - targets; scale = float(weight) / len(factors)
    for edge, rows in enumerate(residual):
        for factor, value in zip(factors, rows):
            gradient[edge] += scale * (1.0 - factor) * value
            gradient[(edge + 1) % len(points)] += scale * factor * value
    return gradient


def _add_sample_gram(matrix, settings, weight, factors):
    count = len(matrix) if settings.topology is V2Topology.CYCLIC else len(matrix) - 1
    scale = float(weight) / len(factors)
    for edge in range(count):
        indices = (edge, (edge + 1) % len(matrix))
        for factor in factors:
            vector = np.asarray((1.0 - factor, factor)); matrix[np.ix_(indices, indices)] += scale * np.outer(vector, vector)


def _readonly(values):
    output = np.ascontiguousarray(values); output.setflags(write=False); return output
