from dataclasses import dataclass

from .soft_tissue_model import Vec3
from .soft_tissue_surface_field import boundary_edges as oriented_boundary_edges


Face = tuple[int, ...]
Edge = tuple[int, int]
_EPS = 1.0e-12


@dataclass(frozen=True)
class SurfaceLayerProfile:
    max_thickness: float = 0.2
    min_thickness: float = 0.006
    thickness_power: float = 0.8


@dataclass(frozen=True)
class SurfaceLayerMesh:
    vertices: tuple[Vec3, ...]
    faces: tuple[Face, ...]
    base_vertex_count: int
    thicknesses: tuple[float, ...]


def validate_surface_layer(points, normals, faces, boundary_edges, weights, profile):
    errors = []
    if len(points) < 3 or len(points) != len(normals) or len(points) != len(weights):
        errors.append("surface requires matching point, normal, and weight arrays")
    if profile.max_thickness <= 0.0 or not 0.0 <= profile.min_thickness <= profile.max_thickness:
        errors.append("surface thickness range is invalid")
    if profile.thickness_power <= 0.0:
        errors.append("thickness power must be positive")
    errors += _topology_errors(len(points), faces, boundary_edges)
    errors += _orientation_errors(faces)
    if any(not 0.0 <= float(value) <= 1.0 for value in weights):
        errors.append("thickness weights must be between zero and one")
    return tuple(errors)


def _orientation_errors(faces):
    uses = {}
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            uses.setdefault(tuple(sorted((a, b))), []).append((a, b))
    if any(len(rows) > 2 or len(rows) == 2 and rows[0] != rows[1][::-1] for rows in uses.values()):
        return ["surface faces require consistent manifold winding"]
    return []


def inflate_surface_layer(points, normals, faces, boundary_edges, weights, profile):
    errors = validate_surface_layer(points, normals, faces, boundary_edges, weights, profile)
    if errors:
        raise ValueError("; ".join(errors))
    front = tuple(_front_point(point, normal, weight, profile) for point, normal, weight in zip(points, normals, weights))
    backing = tuple(_vec(point) for point in points)
    count = len(points)
    shell_faces = tuple(tuple(face) for face in faces) + tuple(_back_face(face, count) for face in faces)
    sides = tuple(_side_face(edge, count) for edge in oriented_boundary_edges((), faces))
    thicknesses = tuple(surface_thickness(weight, profile) for weight in weights)
    return SurfaceLayerMesh(front + backing, shell_faces + sides, count, thicknesses)


def backing_vertex_indices(mesh):
    count = int(mesh.base_vertex_count)
    return tuple(range(count, count * 2))


def perimeter_vertex_indices(mesh, boundary_edges):
    base = sorted({int(index) for edge in boundary_edges for index in edge})
    return tuple(base + [mesh.base_vertex_count + index for index in base])


def _front_point(point, normal, weight, profile):
    unit_normal = _normalize(normal)
    outward = _scale(unit_normal, surface_thickness(weight, profile))
    return _add(_vec(point), outward)


def surface_thickness(weight, profile):
    factor = max(0.0, min(1.0, float(weight))) ** profile.thickness_power
    return profile.min_thickness + (profile.max_thickness - profile.min_thickness) * factor


def _topology_errors(count, faces, boundary_edges):
    errors = []
    if not faces or any(len(face) < 3 for face in faces):
        errors.append("surface requires polygon faces")
    indices = tuple(index for face in faces for index in face)
    indices += tuple(index for edge in boundary_edges for index in edge)
    if indices and (min(indices) < 0 or max(indices) >= count):
        errors.append("surface topology contains an invalid vertex index")
    return errors


def _back_face(face, count):
    return tuple(int(index) + count for index in reversed(face))


def _side_face(edge, count):
    first, second = int(edge[0]), int(edge[1])
    return second, first, first + count, second + count


def _vec(value):
    return tuple(float(value[index]) for index in range(3))


def _add(a, b):
    return tuple(float(a[index]) + float(b[index]) for index in range(3))


def _sub(a, b):
    return tuple(float(a[index]) - float(b[index]) for index in range(3))


def _scale(value, factor):
    return tuple(float(component) * float(factor) for component in value)


def _dot(a, b):
    return sum(float(a[index]) * float(b[index]) for index in range(3))


def _normalize(value):
    result = _normalize_or_zero(value)
    if result == (0.0, 0.0, 0.0):
        raise ValueError("surface frame contains a zero-length normal")
    return result


def _normalize_or_zero(value):
    length = _dot(value, value) ** 0.5
    return (0.0, 0.0, 0.0) if length <= _EPS else _scale(value, 1.0 / length)
