from dataclasses import dataclass
import math

from .soft_tissue_model import Vec3


Face = tuple[int, ...]
_EPS = 1.0e-12


@dataclass(frozen=True)
class CurveRidgeProfile:
    half_width: float = 0.08
    depth: float = 0.12
    profile_power: float = 0.65
    profile_segments: int = 9
    endpoint_taper: float = 0.16
    cyclic: bool = False


@dataclass(frozen=True)
class CurveRidgeMesh:
    vertices: tuple[Vec3, ...]
    faces: tuple[Face, ...]
    ring_size: int


def validate_curve_ridge(points, normals, profile):
    errors = []
    if len(points) < 2 or len(points) != len(normals):
        errors.append("curve requires matching point and normal arrays")
    if profile.half_width <= 0.0 or profile.depth <= 0.0:
        errors.append("profile width and depth must be positive")
    if profile.profile_segments < 3:
        errors.append("profile requires at least three segments")
    if not 0.0 <= profile.endpoint_taper <= 1.0:
        errors.append("endpoint taper must be between zero and one")
    return tuple(errors)


def inflate_curve_ridge(points, normals, profile):
    errors = validate_curve_ridge(points, normals, profile)
    if errors:
        raise ValueError("; ".join(errors))
    rings = tuple(_profile_ring(points, normals, profile, index) for index in range(len(points)))
    vertices = tuple(point for ring in rings for point in ring)
    faces = _front_faces(len(rings), len(rings[0]), profile.cyclic)
    faces += _back_faces(len(rings), len(rings[0]), profile.cyclic)
    caps = () if profile.cyclic else _end_caps(len(rings), len(rings[0]))
    return CurveRidgeMesh(vertices, faces + caps, len(rings[0]))


def backing_vertex_indices(mesh):
    rings = len(mesh.vertices) // mesh.ring_size
    return tuple(index * mesh.ring_size + edge for index in range(rings) for edge in (0, mesh.ring_size - 1))


def commissure_vertex_indices(mesh):
    rings = len(mesh.vertices) // mesh.ring_size
    first = tuple(range(mesh.ring_size))
    last = tuple((rings - 1) * mesh.ring_size + index for index in range(mesh.ring_size))
    return first + last


def geometric_curve_relaxation(mesh, sagginess, gravity, fixed_indices=(), sag_limit=0.0, profile_depth=None):
    fixed = {int(value) for value in fixed_indices}
    depth = _profile_depth(mesh) if profile_depth is None else float(profile_depth)
    amount = float(sagginess) * depth
    amount = min(amount, sag_limit) if sag_limit > 0.0 else amount
    direction = _normalize(gravity)
    return tuple(point if index in fixed else _add(point, _scale(direction, amount * _bulge_weight(mesh, index)))
                 for index, point in enumerate(mesh.vertices))


def _profile_depth(mesh):
    return max((_distance(mesh.vertices[index], mesh.vertices[index - index % mesh.ring_size])
                for index in range(len(mesh.vertices))), default=0.0)


def _bulge_weight(mesh, index):
    slot = int(index) % int(mesh.ring_size)
    phase = slot / max(1, mesh.ring_size - 1)
    return max(0.0, 1.0 - abs(phase * 2.0 - 1.0))


def _profile_ring(points, normals, profile, index):
    point = _vec(points[index])
    normal = _normalize(normals[index])
    tangent = _curve_tangent(points, index, profile.cyclic)
    lateral = _normalize(_cross(normal, tangent))
    taper = 1.0 if profile.cyclic else _taper(index, len(points), profile.endpoint_taper)
    return tuple(_profile_point(point, normal, lateral, profile, taper, value) for value in _profile_values(profile))


def _profile_point(center, normal, lateral, profile, taper, value):
    bulge = max(0.0, 1.0 - value * value) ** profile.profile_power
    across = _scale(lateral, value * profile.half_width * taper)
    outward = _scale(normal, profile.depth * taper * bulge)
    return _add(_add(center, across), outward)


def _profile_values(profile):
    count = int(profile.profile_segments)
    return tuple(-1.0 + (2.0 * index / (count - 1)) for index in range(count))


def _taper(index, count, endpoint):
    phase = math.sin(math.pi * index / max(1, count - 1))
    return float(endpoint) + (1.0 - float(endpoint)) * max(0.0, phase) ** 0.65


def _curve_tangent(points, index, cyclic=False):
    before = points[(index - 1) % len(points)] if cyclic else points[max(0, index - 1)]
    after = points[(index + 1) % len(points)] if cyclic else points[min(len(points) - 1, index + 1)]
    return _normalize(_sub(after, before))


def _front_faces(rings, size, cyclic=False):
    pairs = _ring_pairs(rings, cyclic)
    return tuple((a * size + j, b * size + j, b * size + j + 1, a * size + j + 1)
                 for a, b in pairs for j in range(size - 1))


def _back_faces(rings, size, cyclic=False):
    return tuple((a * size, a * size + size - 1, b * size + size - 1, b * size)
                 for a, b in _ring_pairs(rings, cyclic))


def _ring_pairs(rings, cyclic):
    pairs = [(index, index + 1) for index in range(rings - 1)]
    return tuple(pairs + ([(rings - 1, 0)] if cyclic else []))


def _end_caps(rings, size):
    first = tuple(reversed(range(size)))
    last = tuple((rings - 1) * size + index for index in range(size))
    return first, last


def _vec(value):
    return tuple(float(value[index]) for index in range(3))


def _add(a, b):
    return tuple(a[index] + b[index] for index in range(3))


def _sub(a, b):
    return tuple(float(a[index]) - float(b[index]) for index in range(3))


def _scale(value, factor):
    return tuple(float(component) * float(factor) for component in value)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _normalize(value):
    length = sum(float(component) ** 2 for component in value) ** 0.5
    if length <= _EPS:
        raise ValueError("curve frame contains a zero-length direction")
    return _scale(value, 1.0 / length)


def _distance(a, b):
    return sum((float(a[index]) - float(b[index])) ** 2 for index in range(3)) ** 0.5
