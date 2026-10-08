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
    report: dict = None


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
    points = points - points.mean(axis=0)
    cross = np.cross(points[tri[:, 1]], points[tri[:, 2]])
    return float(np.sum(np.einsum("ij,ij->i", points[tri[:, 0]], cross)) / 6.0)


def solve_static_pouch(vertices, faces, fixed_indices, settings, tethers=()):
    return solve_static_tissue(vertices, faces, fixed_indices, settings, tethers).vertices


def solve_static_tissue(vertices, faces, fixed_indices, settings, tethers=(), tolerance=1.0e-5, fixed_goals=None):
    from .soft_tissue_native import solve
    errors = validate_static_pouch(vertices, faces, fixed_indices, settings, tethers)
    if errors:
        raise ValueError("; ".join(errors))
    settings = settings if _watertight(faces) else replace(settings, volume_stiffness=0.0)
    values, report = solve(vertices, triangulate_faces(faces), fixed_indices, settings, tethers,
                           tolerance, fixed_goals=fixed_goals)
    return StaticSolveResult(values, report["iterations"], report["max_displacement"],
                             report["status"] == "CONVERGED", report)


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


def constraint_pass_stiffness(value, iterations, passes):
    strength = max(0.0, min(1.0, float(value)))
    count = max(1, int(iterations) * int(passes))
    return 1.0 - (1.0 - strength) ** (1.0 / count)


def _tether_errors(vertices, tethers):
    errors = []
    for tether in tethers:
        if not 0 <= int(tether.vertex_index) < len(vertices):
            errors.append("tether vertex index is invalid")
        if tether.rest_length < 0.0 or not 0.0 <= tether.stiffness <= 1.0:
            errors.append("tether parameters are invalid")
    return errors
