from dataclasses import dataclass

from .soft_tissue_model import Vec3
from .soft_tissue_static_pouch import StaticSolveResult, triangulate_faces


@dataclass(frozen=True)
class StaticEnvelopeSettings:
    iterations: int = 110
    constraint_passes: int = 4
    gravity_step: float = 0.0015
    shape_retention: float = 0.5
    volume_retention: float = 0.9
    gravity: Vec3 = (0.0, 0.0, -1.0)
    seed_fraction: float = 0.35
    growth_fraction: float = 0.55
    velocity_retention: float = 0.15
    surface_slack: float = 0.0


def solve_static_envelope(vertices, faces, fixed_indices, surface_count, settings,
                          tethers=(), tolerance=1.0e-5, fixed_goals=None):
    from .soft_tissue_native import solve
    errors = validate_static_envelope(vertices, faces, fixed_indices, surface_count, settings, tethers)
    if errors:
        raise ValueError("; ".join(errors))
    values, report = solve(vertices, triangulate_faces(faces), fixed_indices, settings, tethers,
                           tolerance, surface_count, fixed_goals)
    return StaticSolveResult(values, report["iterations"], report["max_displacement"],
                             report["status"] == "CONVERGED", report)


def validate_static_envelope(vertices, faces, fixed_indices, count, settings, tethers):
    errors = _topology_errors(vertices, faces, fixed_indices, count, tethers)
    values = (settings.shape_retention, settings.volume_retention, settings.seed_fraction,
              settings.growth_fraction, settings.velocity_retention, settings.surface_slack)
    if settings.iterations < 1 or settings.constraint_passes < 1 or settings.gravity_step < 0.0:
        errors.append("static envelope iteration settings are invalid")
    if any(not 0.0 <= float(value) <= 1.0 for value in values):
        errors.append("static envelope material settings must be normalized")
    return tuple(errors)


def _topology_errors(vertices, faces, fixed, count, tethers):
    errors = []
    if int(count) < 3 or int(count) * 2 != len(vertices) or not faces:
        errors.append("static envelope requires paired front and backing surfaces")
    topology = tuple(int(value) for face in faces for value in face)
    indices = topology + tuple(int(value) for value in fixed) + tuple(int(row.vertex_index) for row in tethers)
    if indices and (min(indices) < 0 or max(indices) >= len(vertices)):
        errors.append("static envelope constraint index is invalid")
    if not any(face and all(int(value) < int(count) for value in face) for face in faces):
        errors.append("static envelope requires a front surface")
    if any(row.rest_length < 0.0 or not 0.0 <= row.stiffness <= 1.0 for row in tethers):
        errors.append("static envelope tether parameters are invalid")
    return errors
