"""Frozen pre-migration solver for numerical regression only."""
from dataclasses import dataclass
import numpy as np
from core.vcp.soft_tissue_static_pouch import mesh_volume, triangulate_faces, constraint_pass_stiffness
_EPS = 1.e-12
_MAX_EDGE_SLACK = .25
_MIN_TENSION_FACTOR = .5

@dataclass
class _EnvelopeState:
    rest: np.ndarray
    points: np.ndarray
    velocity: np.ndarray
    triangles: np.ndarray
    surface: np.ndarray
    edges: np.ndarray
    rest_lengths: np.ndarray
    inverse_mass: np.ndarray
    load: np.ndarray
    backing: np.ndarray
    normals: np.ndarray
    fixed: np.ndarray
    start_volume: float
    target_volume: float


def _create_state(vertices, faces, fixed_indices, count, settings):
    rest = np.asarray(vertices, dtype=np.float64)
    triangles = np.asarray(triangulate_faces(faces), dtype=np.int64)
    surface = triangles[np.all(triangles < int(count), axis=1)]
    fixed = _fixed_mask(len(rest), count, fixed_indices)
    points, backing, normals = _seed_points(rest, count, fixed, settings.seed_fraction)
    edges = _surface_edges(surface)
    inverse_mass = (~fixed).astype(np.float64)
    load = _column_load(rest, surface, count, inverse_mass)
    volumes = mesh_volume(points, triangles), mesh_volume(rest, triangles)
    return _EnvelopeState(rest, points, np.zeros_like(rest), triangles, surface, edges,
                          _edge_lengths(rest, edges), inverse_mass, load, backing,
                          normals, fixed, *volumes)


def _fixed_mask(total, count, fixed_indices):
    fixed = np.zeros(int(total), dtype=bool)
    fixed[int(count):] = True
    fixed[np.asarray(tuple(fixed_indices), dtype=np.int64)] = True
    return fixed


def _seed_points(rest, count, fixed, fraction):
    backing = rest[int(count):int(count) * 2].copy()
    delta = rest[:int(count)] - backing
    lengths = np.maximum(np.linalg.norm(delta, axis=1), _EPS)
    normals = delta / lengths[:, None]
    points = rest.copy()
    movable = ~fixed[:int(count)]
    points[:int(count)][movable] = backing[movable] + float(fraction) * delta[movable]
    return points, backing, normals


def _surface_edges(triangles):
    values = {tuple(sorted((int(row[index]), int(row[(index + 1) % 3]))))
              for row in triangles for index in range(3)}
    return np.asarray(sorted(values), dtype=np.int64)


def _edge_lengths(points, edges):
    return np.linalg.norm(points[edges[:, 1]] - points[edges[:, 0]], axis=1)


def _column_load(rest, triangles, count, inverse_mass):
    load = np.zeros(len(rest), dtype=np.float64)
    backing = rest[int(count):int(count) * 2]
    areas = _triangle_areas(backing, triangles)
    thickness = np.linalg.norm(rest[:int(count)] - backing, axis=1)
    prism = areas * np.mean(thickness[triangles], axis=1)
    for corner in range(3):
        np.add.at(load, triangles[:, corner], prism / 3.0)
    scale = _load_scale(backing, thickness)
    return _normalized_load(load, inverse_mass, scale)


def _triangle_areas(points, triangles):
    left = points[triangles[:, 1]] - points[triangles[:, 0]]
    right = points[triangles[:, 2]] - points[triangles[:, 0]]
    return 0.5 * np.linalg.norm(np.cross(left, right), axis=1)


def _load_scale(backing, thickness):
    span = np.max(backing, axis=0) - np.min(backing, axis=0)
    base_scale = max(float(np.linalg.norm(span)), _EPS)
    ratio = 2.0 * float(np.max(thickness)) / base_scale
    return max(0.5, min(4.0, ratio))


def _normalized_load(load, inverse_mass, scale):
    active = inverse_mass > 0.0
    mean = float(np.mean(load[active])) if np.any(active) else 1.0
    values = load / max(mean, _EPS)
    values[active] = float(scale) * np.clip(values[active], 0.2, 5.0)
    return values


def _solve(state, settings, tethers, tolerance):
    change = 0.0
    settle_start = max(1, round(settings.iterations * settings.growth_fraction))
    threshold = _effective_tolerance(settings.gravity_step, tolerance)
    for iteration in range(settings.iterations):
        before = state.points.copy()
        target = _growth_targets(state, iteration, settle_start)
        _predict(state, settings)
        _project_passes(state, target, settings, tethers)
        _update_velocity(state, before, settings.velocity_retention)
        change = _max_distance(state.points, before)
        if iteration >= settle_start and change <= threshold:
            return iteration + 1, change
    return settings.iterations, change


def _effective_tolerance(step, tolerance):
    return float(tolerance) if step <= 0.0 else min(float(tolerance), float(step) * 0.01)


def _finalize_volume(state, settings):
    for _ in range(max(12, settings.constraint_passes * 8)):
        _project_volume(state, state.target_volume, settings.volume_retention)
        _project_host_side(state)
        _project_gravity_support(state, settings.gravity)
        state.points[state.fixed] = state.rest[state.fixed]
        if _relative_volume_error(state) <= 1.0e-7:
            return


def _relative_volume_error(state):
    current = mesh_volume(state.points, state.triangles)
    return abs(current - state.target_volume) / max(abs(state.target_volume), _EPS)


def _growth_targets(state, iteration, count):
    value = max(0.0, min(1.0, (iteration + 1) / max(1, count)))
    smooth = value * value * (3.0 - 2.0 * value)
    return state.start_volume + smooth * (state.target_volume - state.start_volume)


def _predict(state, settings):
    gravity = _unit_vector(settings.gravity)
    state.velocity += float(settings.gravity_step) * state.load[:, None] * gravity[None, :]
    state.points += state.inverse_mass[:, None] * state.velocity
    state.points[state.fixed] = state.rest[state.fixed]


def _project_passes(state, target, settings, tethers):
    for pass_index in range(settings.constraint_passes):
        if pass_index % 2:
            _project_volume(state, target, settings.volume_retention)
        _project_edges(state, settings)
        _project_surface_tension(state, settings)
        _project_tethers(state, tethers, settings)
        if not pass_index % 2:
            _project_volume(state, target, settings.volume_retention)
        _project_host_side(state)
        _project_gravity_support(state, settings.gravity)
        state.points[state.fixed] = state.rest[state.fixed]


def _project_edges(state, settings):
    first, second = state.edges[:, 0], state.edges[:, 1]
    delta = state.points[second] - state.points[first]
    lengths = np.maximum(np.linalg.norm(delta, axis=1), _EPS)
    strain = _slack_strain(lengths, state.rest_lengths, settings.surface_slack)
    strength = _edge_strength(strain, settings.shape_retention, settings.constraint_passes)
    weight = state.inverse_mass[first] + state.inverse_mass[second]
    scale = strength * strain / (lengths * np.maximum(weight, _EPS))
    _scatter_edges(state, first, second, delta * scale[:, None])


def _slack_strain(lengths, rest_lengths, slack):
    original = lengths - rest_lengths
    permitted = lengths - rest_lengths * (1.0 + _MAX_EDGE_SLACK * float(slack))
    return np.where(original > 0.0, np.maximum(permitted, 0.0), original)


def _edge_strength(strain, retention, passes):
    stretch = 0.08 + 0.30 * float(retention)
    compression = 0.005 * float(retention)
    total = np.where(strain > 0.0, stretch, compression)
    return 1.0 - np.power(1.0 - total, 1.0 / max(1, int(passes)))


def _unit_vector(value):
    vector = np.asarray(value, dtype=np.float64)
    length = float(np.linalg.norm(vector))
    return np.zeros(3, dtype=np.float64) if length <= _EPS else vector / length


def _scatter_edges(state, first, second, correction):
    updates = np.zeros_like(state.points)
    degree = np.zeros(len(state.points), dtype=np.float64)
    np.add.at(updates, first, state.inverse_mass[first, None] * correction)
    np.add.at(updates, second, -state.inverse_mass[second, None] * correction)
    np.add.at(degree, first, state.inverse_mass[first])
    np.add.at(degree, second, state.inverse_mass[second])
    state.points += updates / np.maximum(1.0, degree)[:, None]


def _project_volume(state, target, retention):
    gradients = _volume_gradients(state.points, state.triangles)
    denominator = float(np.sum(state.inverse_mass[:, None] * gradients * gradients))
    if denominator <= _EPS:
        return
    difference = mesh_volume(state.points, state.triangles) - float(target)
    state.points -= float(retention) * difference * state.inverse_mass[:, None] * gradients / denominator


def _project_surface_tension(state, settings):
    gradients, counts = _area_gradients(state.points, state.surface)
    factor = 1.0 - (1.0 - _MIN_TENSION_FACTOR) * float(settings.surface_slack)
    total = (0.10 + 0.40 * float(settings.shape_retention)) * factor
    strength = 1.0 - (1.0 - total) ** (1.0 / max(1, settings.constraint_passes))
    movable = state.inverse_mass > 0.0
    direction = gradients / np.maximum(counts, 1.0)[:, None]
    state.points[movable] -= strength * direction[movable]


def _area_gradients(points, triangles):
    first, second, third = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    normal = _triangle_normals(points, triangles)
    values = (np.cross(normal, points[third] - points[second]),
              np.cross(normal, points[first] - points[third]),
              np.cross(normal, points[second] - points[first]))
    gradients, counts = np.zeros_like(points), np.zeros(len(points), dtype=np.float64)
    for indices, value in zip((first, second, third), values):
        np.add.at(gradients, indices, value * 0.5)
        np.add.at(counts, indices, 1.0)
    return gradients, counts


def _triangle_normals(points, triangles):
    left = points[triangles[:, 1]] - points[triangles[:, 0]]
    right = points[triangles[:, 2]] - points[triangles[:, 0]]
    values = np.cross(left, right)
    return values / np.maximum(np.linalg.norm(values, axis=1), _EPS)[:, None]


def _volume_gradients(points, triangles):
    gradients = np.zeros_like(points)
    first, second, third = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    np.add.at(gradients, first, np.cross(points[second], points[third]) / 6.0)
    np.add.at(gradients, second, np.cross(points[third], points[first]) / 6.0)
    np.add.at(gradients, third, np.cross(points[first], points[second]) / 6.0)
    return gradients


def _project_tethers(state, tethers, settings):
    for tether in tethers:
        strength = constraint_pass_stiffness(tether.stiffness, settings.iterations,
                                             settings.constraint_passes)
        _project_tether(state, tether, strength)


def _project_tether(state, tether, strength):
    index = int(tether.vertex_index)
    if state.inverse_mass[index] <= 0.0:
        return
    delta = state.points[index] - np.asarray(tether.anchor, dtype=np.float64)
    length = max(float(np.linalg.norm(delta)), _EPS)
    excess = length - float(tether.rest_length)
    state.points[index] -= float(strength) * excess * delta / length


def _project_host_side(state):
    count = len(state.backing)
    delta = state.points[:count] - state.backing
    distance = np.einsum("ij,ij->i", delta, state.normals)
    movable = state.inverse_mass[:count] > 0.0
    correction = np.maximum(0.0, -distance)
    state.points[:count][movable] += correction[movable, None] * state.normals[movable]


def _project_gravity_support(state, gravity):
    direction = _unit_vector(gravity)
    if not np.any(direction):
        return
    count = len(state.backing)
    tangent = np.abs(state.normals @ direction) < 0.5
    rise = (state.points[:count] - state.rest[:count]) @ (-direction)
    movable = (state.inverse_mass[:count] > 0.0) & tangent & (rise > 0.0)
    state.points[:count][movable] += rise[movable, None] * direction


def _update_velocity(state, before, retention):
    state.velocity = float(retention) * (state.points - before)
    state.velocity[state.fixed] = 0.0


def _max_distance(first, second):
    values = np.linalg.norm(first - second, axis=1)
    return 0.0 if not len(values) else float(np.max(values))


