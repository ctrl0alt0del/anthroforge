from dataclasses import dataclass, field

from .soft_tissue_model import SolverMode, Vec3
from .soft_tissue_static_pouch import StaticPouchSettings, StaticTether, solve_static_pouch
from .soft_tissue_surface_inflation import SurfaceLayerMesh, SurfaceLayerProfile, inflate_surface_layer


@dataclass(frozen=True)
class GeometricRelaxationSpec:
    sag_fraction: float = 0.0
    gravity: Vec3 = (0.0, 0.0, -1.0)
    sag_limit: float = 0.0


@dataclass(frozen=True)
class SurfaceTissuePipelineSpec:
    mode: SolverMode = SolverMode.NONE
    inflation: SurfaceLayerProfile = field(default_factory=SurfaceLayerProfile)
    geometric: GeometricRelaxationSpec = field(default_factory=GeometricRelaxationSpec)
    static: StaticPouchSettings = field(default_factory=StaticPouchSettings)
    fixed_indices: tuple[int, ...] = ()
    tethers: tuple[StaticTether, ...] = ()


@dataclass(frozen=True)
class SurfaceTissueResult:
    rest: SurfaceLayerMesh
    final_vertices: tuple[Vec3, ...]
    mode: SolverMode


def run_surface_tissue_pipeline(points, normals, faces, boundary_edges, weights, spec):
    rest = inflate_surface_layer(points, normals, faces, boundary_edges, weights, spec.inflation)
    final = _relax_surface(rest, normals, weights, spec)
    return SurfaceTissueResult(rest, final, spec.mode)


def surface_fixed_indices(vertex_count, boundary_edges):
    backing = range(int(vertex_count), int(vertex_count) * 2)
    boundary = {int(index) for edge in boundary_edges for index in edge}
    perimeter = boundary | {int(vertex_count) + index for index in boundary}
    return tuple(sorted(set(backing) | perimeter))


def _relax_surface(rest, normals, weights, spec):
    if spec.mode == SolverMode.NONE:
        return rest.vertices
    if spec.mode == SolverMode.GEOMETRIC:
        return _geometric_vertices(rest, normals, weights, spec.geometric)
    if spec.mode == SolverMode.STATIC_PBD:
        return solve_static_pouch(rest.vertices, rest.faces, spec.fixed_indices, spec.static, spec.tethers)
    raise NotImplementedError(f"surface relaxation mode {spec.mode.value} is not implemented")


def _geometric_vertices(rest, normals, weights, spec):
    front = tuple(_relax_point(point, normal, weight, rest, spec)
                  for point, normal, weight in zip(rest.vertices, normals, weights))
    return front + rest.vertices[rest.base_vertex_count:]


def _relax_point(point, normal, weight, rest, spec):
    tangent = _tangent_gravity(normal, spec.gravity)
    amount = spec.sag_fraction * max(rest.thicknesses) * float(weight)
    if spec.sag_limit > 0.0:
        amount = min(amount, spec.sag_limit)
    return _add(point, _scale(tangent, amount))


def _tangent_gravity(normal, gravity):
    unit_normal = _normalize(normal)
    unit_gravity = _normalize(gravity)
    tangent = _sub(unit_gravity, _scale(unit_normal, _dot(unit_gravity, unit_normal)))
    return _normalize_or_zero(tangent)


def _normalize(value):
    result = _normalize_or_zero(value)
    if result == (0.0, 0.0, 0.0):
        raise ValueError("surface relaxation vector cannot be zero length")
    return result


def _normalize_or_zero(value):
    length = _dot(value, value) ** 0.5
    return (0.0, 0.0, 0.0) if length <= 1.0e-12 else _scale(value, 1.0 / length)


def _add(a, b):
    return tuple(float(a[index]) + float(b[index]) for index in range(3))


def _sub(a, b):
    return tuple(float(a[index]) - float(b[index]) for index in range(3))


def _scale(value, factor):
    return tuple(float(component) * float(factor) for component in value)


def _dot(a, b):
    return sum(float(a[index]) * float(b[index]) for index in range(3))
