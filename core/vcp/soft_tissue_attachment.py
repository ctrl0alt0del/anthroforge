from dataclasses import dataclass
from hashlib import sha256
import json

from .soft_tissue_model import AttachmentMode, AttachmentSpec, TargetKind, TargetSurface, Vec3


Triangle = tuple[int, int, int]
_EPS = 1e-12


class AttachmentError(ValueError):
    pass


class AttachmentTopologyError(AttachmentError):
    pass


@dataclass(frozen=True)
class SurfaceMesh:
    target_kind: TargetKind
    target_id: str
    target_surface: TargetSurface
    vertices: tuple[Vec3, ...]
    triangles: tuple[Triangle, ...]


@dataclass(frozen=True)
class TriangleHit:
    tri_vidx: Triangle
    tri_weights: Vec3
    point: Vec3
    distance_squared: float


@dataclass(frozen=True)
class SurfaceBinding:
    target_kind: TargetKind
    target_id: str
    target_surface: TargetSurface
    tri_vidx: Triangle
    tri_weights: Vec3
    normal_offset: float
    topology_signature: str


@dataclass(frozen=True)
class AttachmentEvaluation:
    point: Vec3
    binding: SurfaceBinding


def surface_topology_signature(surface):
    payload = {
        "vertex_count": len(surface.vertices),
        "triangles": [list(tri) for tri in surface.triangles],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def validate_surface(surface):
    errors = []
    if not surface.vertices:
        errors.append("surface requires vertices")
    if not surface.triangles:
        errors.append("surface requires triangles")
    for tri in surface.triangles:
        errors += _triangle_errors(surface, tri)
    return tuple(errors)


def nearest_surface_point(surface, point):
    errors = validate_surface(surface)
    if errors:
        raise AttachmentError("; ".join(errors))
    hits = [_triangle_hit(surface, tri, point) for tri in surface.triangles]
    return min(hits, key=lambda hit: hit.distance_squared)


def capture_surface_binding(surface, attachment, point):
    _require_surface_attachment(attachment)
    _require_surface_match(surface, attachment)
    hit = nearest_surface_point(surface, point)
    return SurfaceBinding(
        attachment.target_kind, attachment.target_id, attachment.target_surface,
        hit.tri_vidx, hit.tri_weights, float(attachment.normal_offset),
        surface_topology_signature(surface),
    )


def resolve_surface_binding(surface, binding):
    _require_surface_match(surface, binding)
    _require_current_topology(surface, binding)
    tri = _triangle_vertices(surface, binding.tri_vidx)
    point = _weighted_point(tri, binding.tri_weights)
    normal = _triangle_normal(*tri)
    return _add(point, _scale(normal, binding.normal_offset))


def apply_surface_attachment(surface, attachment, binding, point):
    _require_binding_match(attachment, binding)
    if attachment.mode == AttachmentMode.FREE:
        return AttachmentEvaluation(_vec(point), binding)
    target = resolve_surface_binding(surface, binding)
    output = _lerp(point, target, attachment.strength) if attachment.mode == AttachmentMode.SOFT else target
    return AttachmentEvaluation(output, binding)


def _triangle_errors(surface, tri):
    if len(tuple(tri)) != 3:
        return ["triangles require three vertex indices"]
    if min(tri) < 0 or max(tri) >= len(surface.vertices):
        return ["triangle vertex index is out of range"]
    a, b, c = _triangle_vertices(surface, tri)
    return ["degenerate triangle is not supported"] if _length_squared(_cross(_sub(b, a), _sub(c, a))) <= _EPS else []


def _triangle_hit(surface, tri, point):
    vertices = _triangle_vertices(surface, tri)
    weights = _projected_weights(point, *vertices)
    if weights is None or min(weights) < 0.0:
        weights = min(_edge_weights(point, *vertices), key=lambda item: item[0])[1]
    projected = _weighted_point(vertices, weights)
    return TriangleHit(tuple(tri), weights, projected, _distance_squared(point, projected))


def _projected_weights(point, a, b, c):
    ab, ac, ap = _sub(b, a), _sub(c, a), _sub(point, a)
    d00, d01, d11 = _dot(ab, ab), _dot(ab, ac), _dot(ac, ac)
    d20, d21 = _dot(ap, ab), _dot(ap, ac)
    denominator = d00 * d11 - d01 * d01
    if abs(denominator) <= _EPS:
        return None
    v = (d11 * d20 - d01 * d21) / denominator
    w = (d00 * d21 - d01 * d20) / denominator
    return 1.0 - v - w, v, w


def _edge_weights(point, a, b, c):
    pairs = ((a, b, (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
             (b, c, (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
             (c, a, (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)))
    return tuple(_edge_candidate(point, *item) for item in pairs)


def _edge_candidate(point, a, b, wa, wb):
    ab = _sub(b, a)
    denominator = max(_EPS, _dot(ab, ab))
    t = max(0.0, min(1.0, _dot(_sub(point, a), ab) / denominator))
    weights = tuple(wa[i] * (1.0 - t) + wb[i] * t for i in range(3))
    projected = _lerp(a, b, t)
    return _distance_squared(point, projected), weights


def _require_surface_attachment(attachment):
    if attachment.target_kind == TargetKind.NONE or not attachment.target_id:
        raise AttachmentError("surface attachment requires a target")
    if attachment.target_surface == TargetSurface.AUTO:
        raise AttachmentError("surface attachment requires an explicit target surface")


def _require_current_topology(surface, binding):
    current = surface_topology_signature(surface)
    if current != binding.topology_signature:
        raise AttachmentTopologyError("attachment target topology changed")
    _triangle_vertices(surface, binding.tri_vidx)


def _require_binding_match(attachment, binding):
    actual = (binding.target_kind, binding.target_id, binding.target_surface)
    expected = (attachment.target_kind, attachment.target_id, attachment.target_surface)
    if actual != expected:
        raise AttachmentError("binding target does not match attachment")


def _require_surface_match(surface, target):
    actual = (surface.target_kind, surface.target_id, surface.target_surface)
    expected = (target.target_kind, target.target_id, target.target_surface)
    if actual != expected:
        raise AttachmentError("evaluated surface does not match attachment target")


def _triangle_vertices(surface, tri):
    try:
        return tuple(_vec(surface.vertices[index]) for index in tri)
    except (IndexError, TypeError):
        raise AttachmentTopologyError("binding triangle no longer resolves") from None


def _weighted_point(vertices, weights):
    terms = (_scale(vertices[i], float(weights[i])) for i in range(3))
    return _sum_vectors(terms)


def _triangle_normal(a, b, c):
    value = _cross(_sub(b, a), _sub(c, a))
    length = _length_squared(value) ** 0.5
    if length <= _EPS:
        raise AttachmentTopologyError("binding triangle is degenerate")
    return _scale(value, 1.0 / length)


def _sum_vectors(values):
    result = (0.0, 0.0, 0.0)
    for value in values:
        result = _add(result, value)
    return result


def _vec(value):
    return tuple(float(value[i]) for i in range(3))


def _add(a, b):
    return tuple(float(a[i]) + float(b[i]) for i in range(3))


def _sub(a, b):
    return tuple(float(a[i]) - float(b[i]) for i in range(3))


def _scale(value, factor):
    return tuple(float(component) * float(factor) for component in value)


def _dot(a, b):
    return sum(float(a[i]) * float(b[i]) for i in range(3))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _length_squared(value):
    return _dot(value, value)


def _distance_squared(a, b):
    return _length_squared(_sub(a, b))


def _lerp(a, b, factor):
    t = float(factor)
    return tuple(float(a[i]) * (1.0 - t) + float(b[i]) * t for i in range(3))
