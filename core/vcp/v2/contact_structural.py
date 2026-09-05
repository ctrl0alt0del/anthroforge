"""O(N) structural solve with fixed node and chain-midpoint contact slots."""

from dataclasses import dataclass

import numpy as np

from . import structural as base
from .contracts import V2Settings, V2Topology


V2_CONTACT_STRUCTURAL_VERSION = "fiber-v2-contact-structural-1"


@dataclass(frozen=True)
class ContactFactorKey:
    count: int
    topology: str
    free_mask: tuple
    length_weight: float
    bend_weight: float
    rho: float
    node_weight: float
    edge_weight: float


@dataclass(frozen=True)
class ContactSlotEnergy:
    structural: float
    node: float
    edge: float

    @property
    def total(self):
        return self.structural + self.node + self.edge


@dataclass(frozen=True)
class ContactStructuralResult:
    points: np.ndarray
    energy: ContactSlotEnergy
    stationarity_residual: float
    factor_cache_hit: bool
    engine_version: str = V2_CONTACT_STRUCTURAL_VERSION


DEFAULT_CONTACT_FACTOR_CACHE = base.FiberFactorCache()


def solve_contact_structural(reference, current, node_targets, edge_targets, pins=None,
                             settings=None, node_weight=10.0, edge_weight=10.0, cache=None):
    config = _settings(settings); values = base._validated_points(reference)
    current, nodes, edges = _slot_data(values, current, node_targets, edge_targets, config)
    pinned, targets = base._pin_data(pins, len(values)); weights = _weights(node_weight, edge_weight)
    store = DEFAULT_CONTACT_FACTOR_CACHE if cache is None else cache
    solved, hit = _solve(values, nodes, edges, pinned, targets, config, weights, store)
    energy = contact_slot_energy(solved, values, nodes, edges, config, *weights)
    residual = contact_stationarity(solved, values, nodes, edges, pinned, config, *weights)
    return ContactStructuralResult(_readonly(solved), energy, residual, hit)


def contact_slot_energy(points, reference, node_targets, edge_targets, settings=None,
                        node_weight=10.0, edge_weight=10.0):
    config = _settings(settings); values = base._validated_points(points)
    reference, nodes, edges = _slot_data(values, reference, node_targets, edge_targets, config)
    structural = base.structural_energy(values, reference, config).total
    node = float(node_weight) * float(np.sum((values - nodes) ** 2))
    edge = float(edge_weight) * float(np.sum((_midpoints(values, config) - edges) ** 2))
    return ContactSlotEnergy(float(structural), node, edge)


def assemble_contact_matrix(count, settings=None, node_weight=10.0, edge_weight=10.0):
    config = _settings(settings); static = base._static_settings(config)
    matrix = base.assemble_normal_matrix(int(count), static)
    matrix += float(node_weight) * np.eye(int(count))
    _add_edge_gram(matrix, config, float(edge_weight))
    return matrix


def contact_stationarity(points, reference, node_targets, edge_targets, pinned=(), settings=None,
                         node_weight=10.0, edge_weight=10.0):
    config = _settings(settings); values = base._validated_points(points)
    reference, nodes, edges = _slot_data(values, reference, node_targets, edge_targets, config)
    gradient = _gradient(values, reference, nodes, edges, config, node_weight, edge_weight)
    mask = np.ones(len(values), dtype=bool); mask[base._validated_pin_indices(pinned, len(values))] = False
    rows = gradient[mask]
    return float(np.max(np.linalg.norm(rows, axis=1))) if len(rows) else 0.0


def clear_contact_factor_cache():
    DEFAULT_CONTACT_FACTOR_CACHE.clear()


def contact_factor_cache_stats():
    return DEFAULT_CONTACT_FACTOR_CACHE.stats()


def _settings(settings):
    if settings is None:
        return V2Settings()
    if not isinstance(settings, V2Settings):
        raise ValueError("settings must use the V2Settings contract")
    return settings


def _weights(node_weight, edge_weight):
    values = float(node_weight), float(edge_weight)
    if any(not np.isfinite(value) or value <= 0.0 for value in values):
        raise ValueError("contact slot weights must be finite and positive")
    return values


def _slot_data(reference, current, nodes, edges, settings):
    current = base._validated_points(current); nodes = base._validated_points(nodes)
    edges = np.ascontiguousarray(edges, dtype=np.float64)
    expected = len(reference) if settings.topology is V2Topology.CYCLIC else len(reference) - 1
    if current.shape != reference.shape or nodes.shape != reference.shape:
        raise ValueError("node slot arrays must match the reference")
    if edges.shape != (expected, 3) or not np.isfinite(edges).all():
        raise ValueError("edge slot targets must match chain topology")
    return current, nodes, edges


def _solve(reference, nodes, edges, pinned, targets, settings, weights, cache):
    points = reference.copy(); points[pinned] = targets
    if len(pinned) == len(reference):
        return points, False
    key = _factor_key(len(reference), pinned, settings, weights)
    factor, hit = cache.get_or_build(key, lambda: _build_factor(key))
    rhs = _rhs(reference, nodes, edges, settings, *weights)[factor.free]
    rhs -= base._coupling_product(factor, targets) + base._update_pin_product(factor, targets)
    points[factor.free] = base._solve_factor(factor, rhs); points[pinned] = targets
    return points, hit


def _factor_key(count, pinned, settings, weights):
    mask = np.ones(int(count), dtype=bool); mask[pinned] = False
    return ContactFactorKey(int(count), V2Topology(settings.topology).value,
                            tuple(bool(value) for value in mask), float(settings.length_weight),
                            float(settings.curvature_weight), float(settings.fidelity_weight), *weights)


def _build_factor(key):
    settings = base.StaticFiberSettings(key.length_weight, key.bend_weight, key.rho, key.topology)
    free = np.flatnonzero(np.asarray(key.free_mask)); pinned = np.flatnonzero(~np.asarray(key.free_mask))
    bands = _contact_bands(key.count, settings, key.node_weight, key.edge_weight)
    factors = base._factor_pentadiagonal(*base._reduced_bands(bands, free))
    coupling = base._base_coupling(bands, free, pinned)
    updates = _reduced_updates(key, settings, free, pinned)
    woodbury = base._woodbury_data(factors, updates[0])
    values = (free, pinned, *factors, *coupling, *updates, *woodbury)
    return base._ReducedFactor(*(base._readonly(value) for value in values))


def _contact_bands(count, settings, node_weight, edge_weight):
    diagonal, lower1, lower2 = base._base_bands(count, settings)
    diagonal += float(node_weight); scale = 0.25 * float(edge_weight)
    diagonal[:-1] += scale; diagonal[1:] += scale; lower1[1:] += scale
    return diagonal, lower1, lower2


def _reduced_updates(key, settings, free, pinned):
    updates = base._cyclic_updates(key.count, settings)
    contact = _cyclic_contact_update(key.count, key.topology, key.edge_weight)
    if contact.shape[1]:
        updates = np.column_stack((updates, contact))
    return updates[free].copy(), updates[pinned].copy()


def _cyclic_contact_update(count, topology, weight):
    if topology != base.CYCLIC:
        return np.empty((count, 0), dtype=np.float64)
    column = np.zeros((count, 1), dtype=np.float64); scale = 0.5 * np.sqrt(float(weight))
    column[0, 0] = scale; column[-1, 0] = scale
    return column


def _rhs(reference, nodes, edges, settings, node_weight, edge_weight):
    rhs = float(settings.fidelity_weight) * reference + float(node_weight) * nodes
    scale = 0.5 * float(edge_weight); count = len(reference)
    for edge, target in enumerate(edges):
        rhs[edge] += scale * target; rhs[(edge + 1) % count] += scale * target
    return rhs


def _midpoints(points, settings):
    count = len(points) if settings.topology is V2Topology.CYCLIC else len(points) - 1
    indices = np.arange(count, dtype=np.int64)
    return 0.5 * (points[indices] + points[(indices + 1) % len(points)])


def _gradient(points, reference, nodes, edges, settings, node_weight, edge_weight):
    gradient = base._normal_gradient(points, reference, base._static_settings(settings))
    gradient += float(node_weight) * (points - nodes)
    residual = _midpoints(points, settings) - edges; scale = 0.5 * float(edge_weight)
    for edge, value in enumerate(residual):
        gradient[edge] += scale * value; gradient[(edge + 1) % len(points)] += scale * value
    return gradient


def _add_edge_gram(matrix, settings, weight):
    count = len(matrix) if settings.topology is V2Topology.CYCLIC else len(matrix) - 1
    for edge in range(count):
        indices = (edge, (edge + 1) % len(matrix)); matrix[np.ix_(indices, indices)] += 0.25 * weight


def _readonly(values):
    output = np.ascontiguousarray(values); output.setflags(write=False); return output
