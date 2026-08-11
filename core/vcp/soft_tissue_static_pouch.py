from dataclasses import dataclass, replace

import numpy as np

from .soft_tissue_model import Vec3


@dataclass(frozen=True)
class StaticTether:
    vertex_index: int
    anchor: Vec3
    rest_length: float
    stiffness: float = 0.25


@dataclass(frozen=True)
class StaticPouchSettings:
    iterations: int = 100
    constraint_passes: int = 4
    gravity_step: float = 0.0015
    edge_stiffness: float = 0.5
    volume_stiffness: float = 0.8
    gravity: Vec3 = (0.0, 0.0, -1.0)
    sag_limit: float = 0.0


@dataclass(frozen=True)
class StaticSolveResult:
    vertices: tuple[Vec3, ...]
    iterations: int
    max_displacement: float
    converged: bool


def triangulate_faces(faces):
    triangles = []
    for face in faces:
        triangles += [(int(face[0]), int(face[index]), int(face[index + 1]))
                      for index in range(1, len(face) - 1)]
    return tuple(triangles)


def mesh_volume(vertices, triangles):
    points = np.asarray(vertices, dtype=np.float64)
    tri = np.asarray(triangles, dtype=np.int64)
    if not len(tri):
        return 0.0
    cross = np.cross(points[tri[:, 1]], points[tri[:, 2]])
    return float(np.sum(np.einsum("ij,ij->i", points[tri[:, 0]], cross)) / 6.0)


def solve_static_pouch(vertices, faces, fixed_indices, settings, tethers=()):
    return solve_static_tissue(vertices, faces, fixed_indices, settings, tethers).vertices


def solve_static_tissue(vertices, faces, fixed_indices, settings, tethers=(), tolerance=1.0e-5):
    errors = validate_static_pouch(vertices, faces, fixed_indices, settings, tethers)
    if errors:
        raise ValueError("; ".join(errors))
    rest = np.asarray(vertices, dtype=np.float64)
    triangles = np.asarray(triangulate_faces(faces), dtype=np.int64)
    settings = settings if _watertight(faces) else replace(settings, volume_stiffness=0.0)
    edges = _mesh_edges(triangles)
    lengths = _edge_lengths(rest, edges)
    inverse_mass = _inverse_masses(len(rest), fixed_indices)
    solved, count, displacement = _solve_iterations(rest.copy(), rest, triangles, edges, lengths, inverse_mass, settings, tethers, tolerance)
    values = tuple(tuple(float(value) for value in point) for point in solved)
    return StaticSolveResult(values, count, displacement, displacement <= tolerance)


def _watertight(faces):
    counts = {}
    for face in faces:
        for index in range(len(face)):
            edge = tuple(sorted((int(face[index]), int(face[(index + 1) % len(face)]))))
            counts[edge] = counts.get(edge, 0) + 1
    return bool(counts) and all(value == 2 for value in counts.values())


def gravity_step_from_sagginess(sagginess):
    return 0.0015 * max(0.0, float(sagginess)) / 0.58


def validate_static_pouch(vertices, faces, fixed_indices, settings, tethers):
    errors = []
    triangles = triangulate_faces(faces)
    if len(vertices) < 4 or not triangles:
        errors.append("static pouch requires a closed triangle mesh")
    indices = tuple(index for tri in triangles for index in tri) + tuple(int(index) for index in fixed_indices)
    if indices and (min(indices) < 0 or max(indices) >= len(vertices)):
        errors.append("static pouch topology contains an invalid vertex index")
    if settings.iterations < 1 or settings.constraint_passes < 1 or settings.gravity_step < 0.0:
        errors.append("static pouch iteration settings are invalid")
    if any(not 0.0 <= value <= 1.0 for value in (settings.edge_stiffness, settings.volume_stiffness)):
        errors.append("static pouch stiffness must be between zero and one")
    errors += _tether_errors(vertices, tethers)
    return tuple(errors)


def _solve_iterations(points, rest, triangles, edges, lengths, inverse_mass, settings, tethers, tolerance):
    target_volume = mesh_volume(rest, triangles)
    fixed = inverse_mass == 0.0
    threshold = _convergence_threshold(settings.gravity_step, tolerance)
    displacement = 0.0
    for iteration in range(settings.iterations):
        before = points.copy()
        _apply_gravity(points, inverse_mass, settings)
        for _ in range(settings.constraint_passes):
            _project_constraints(points, rest, triangles, edges, lengths, inverse_mass,
                                 target_volume, settings, tethers)
            points[fixed] = rest[fixed]
        displacement = _max_displacement(points, before)
        if displacement <= threshold:
            return _finalized_result(points, rest, triangles, target_volume, inverse_mass, settings, iteration + 1)
    return _finalized_result(points, rest, triangles, target_volume, inverse_mass, settings, settings.iterations)


def _convergence_threshold(gravity_step, tolerance):
    if float(gravity_step) <= 0.0:
        return float(tolerance)
    return min(float(tolerance), max(float(gravity_step) * 0.01, 1.0e-12))


def _finalized_result(points, rest, triangles, target, inverse_mass, settings, iterations):
    _final_volume_projection(points, triangles, target, inverse_mass, settings)
    return points, iterations, _max_displacement(points, rest)


def _final_volume_projection(points, triangles, target, inverse_mass, settings):
    for _ in range(settings.constraint_passes):
        _project_volume(points, triangles, target, inverse_mass, settings.volume_stiffness)


def _project_constraints(points, rest, triangles, edges, lengths, inverse_mass, target, settings, tethers):
    _project_edges(points, edges, lengths, inverse_mass, settings.edge_stiffness)
    _project_tethers(points, inverse_mass, tethers, settings)
    _project_volume(points, triangles, target, inverse_mass, settings.volume_stiffness)
    _apply_sag_limit(points, rest, inverse_mass, settings.sag_limit)


def _max_displacement(points, before):
    values = np.linalg.norm(points - before, axis=1)
    return 0.0 if not len(values) else float(np.max(values))


def _mesh_edges(triangles):
    edges = {tuple(sorted((int(tri[i]), int(tri[(i + 1) % 3])))) for tri in triangles for i in range(3)}
    return np.asarray(sorted(edges), dtype=np.int64)


def _edge_lengths(points, edges):
    return np.linalg.norm(points[edges[:, 1]] - points[edges[:, 0]], axis=1)


def _inverse_masses(count, fixed_indices):
    values = np.ones(int(count), dtype=np.float64)
    values[np.asarray(tuple(fixed_indices), dtype=np.int64)] = 0.0
    return values


def _apply_gravity(points, inverse_mass, settings):
    gravity = np.asarray(settings.gravity, dtype=np.float64)
    points += settings.gravity_step * inverse_mass[:, None] * gravity[None, :]


def _apply_sag_limit(points, rest, inverse_mass, limit):
    if float(limit) <= 0.0:
        return
    delta = points - rest
    lengths = np.linalg.norm(delta, axis=1)
    scale = np.minimum(1.0, float(limit) / np.maximum(lengths, 1.0e-12))
    movable = inverse_mass > 0.0
    points[movable] = rest[movable] + delta[movable] * scale[movable, None]


def _project_edges(points, edges, rest_lengths, inverse_mass, stiffness):
    first, second = edges[:, 0], edges[:, 1]
    delta = points[second] - points[first]
    lengths = np.maximum(np.linalg.norm(delta, axis=1), 1.0e-12)
    weight = inverse_mass[first] + inverse_mass[second]
    scale = float(stiffness) * (lengths - rest_lengths) / (lengths * np.maximum(weight, 1.0e-12))
    correction = delta * scale[:, None]
    _scatter_edge_corrections(points, first, second, correction, inverse_mass)


def _scatter_edge_corrections(points, first, second, correction, inverse_mass):
    updates = np.zeros_like(points)
    degree = np.zeros(len(points), dtype=np.float64)
    np.add.at(updates, first, inverse_mass[first, None] * correction)
    np.add.at(updates, second, -inverse_mass[second, None] * correction)
    np.add.at(degree, first, inverse_mass[first])
    np.add.at(degree, second, inverse_mass[second])
    points += updates / np.maximum(1.0, degree)[:, None]


def _project_tethers(points, inverse_mass, tethers, settings):
    for tether in tethers:
        strength = constraint_pass_stiffness(tether.stiffness, settings.iterations,
                                             settings.constraint_passes)
        _project_tether(points, inverse_mass, tether, strength)


def _project_tether(points, inverse_mass, tether, strength):
    index = int(tether.vertex_index)
    if inverse_mass[index] <= 0.0:
        return
    delta = points[index] - np.asarray(tether.anchor, dtype=np.float64)
    length = max(float(np.linalg.norm(delta)), 1.0e-12)
    correction = float(strength) * (length - float(tether.rest_length)) * delta / length
    points[index] -= correction


def constraint_pass_stiffness(value, iterations, passes):
    strength = max(0.0, min(1.0, float(value)))
    count = max(1, int(iterations) * int(passes))
    return 1.0 - (1.0 - strength) ** (1.0 / count)


def _project_volume(points, triangles, target, inverse_mass, stiffness):
    gradients = _volume_gradients(points, triangles)
    denominator = float(np.sum(inverse_mass[:, None] * gradients * gradients))
    if denominator <= 1.0e-12:
        return
    difference = mesh_volume(points, triangles) - float(target)
    scale = float(stiffness) * difference / denominator
    points -= scale * inverse_mass[:, None] * gradients


def _volume_gradients(points, triangles):
    gradients = np.zeros_like(points)
    first, second, third = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    np.add.at(gradients, first, np.cross(points[second], points[third]) / 6.0)
    np.add.at(gradients, second, np.cross(points[third], points[first]) / 6.0)
    np.add.at(gradients, third, np.cross(points[first], points[second]) / 6.0)
    return gradients


def _tether_errors(vertices, tethers):
    errors = []
    for tether in tethers:
        if not 0 <= int(tether.vertex_index) < len(vertices):
            errors.append("tether vertex index is invalid")
        if tether.rest_length < 0.0 or not 0.0 <= tether.stiffness <= 1.0:
            errors.append("tether parameters are invalid")
    return errors
