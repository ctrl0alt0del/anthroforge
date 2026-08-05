import numpy as np
from scipy.spatial import cKDTree

from ..topology.bindings import build_topology_guide_binding, build_topology_skin_binding
from .arap import constrained_arap
from .model import WarmInvalidationReason, WarmUpdateStatus, WarmValidationReport
from .signatures import structural_signature

_PROJECTION_STATS = {"bound_vertices": 0, "global_fallback_vertices": 0}


def reproject_topology(vertices, quads, skin_vertices, skin_triangles, skin_binding,
                       guide_binding, old_guides=(), new_guides=(), iterations=3,
                       symmetry_plane=None):
    surface = evaluate_skin_binding(skin_binding, skin_vertices, skin_triangles)
    guided = _guide_prediction(vertices, guide_binding, old_guides, new_guides)
    targets = _blend_constraints(surface, guided, guide_binding)
    current = _relax_project(vertices, quads, targets, skin_vertices,
                             skin_triangles, skin_binding, iterations, guide_binding)
    current = enforce_symmetry(vertices, current, symmetry_plane)
    validation = validate_warm_topology(vertices, quads, current)
    reason = WarmInvalidationReason.NONE if validation.valid else WarmInvalidationReason.VALIDATION_FAILED
    return current, WarmUpdateStatus(validation.valid, "Complete", 1.0,
                                     validation.message, reason), validation


def evaluate_skin_binding(binding, skin_vertices, skin_triangles):
    triangles = np.asarray(skin_vertices)[np.asarray(skin_triangles)[binding.triangle_indices]]
    points = np.einsum("ni,nij->nj", binding.barycentric, triangles)
    normals = _normals(triangles)
    return points + normals * np.asarray(binding.offsets)[:, None]


def rebind_topology(vertices, quads, skin_vertices, skin_triangles, regions,
                    face_guides, guides, predicted=None):
    result = project_and_rebind_topology(vertices, quads, skin_vertices, skin_triangles,
                                         regions, face_guides, guides, predicted)
    return result[1], result[2], result[3], result[4]


def project_and_rebind_topology(vertices, quads, skin_vertices, skin_triangles, regions,
                                face_guides, guides, predicted=None, symmetry_plane=None):
    points = np.asarray(vertices if predicted is None else predicted)
    skin_binding = build_topology_skin_binding(points, skin_vertices, skin_triangles)
    skin_binding = _zero_offset_binding(skin_binding)
    projected = evaluate_skin_binding(skin_binding, skin_vertices, skin_triangles)
    projected = enforce_symmetry(vertices, projected, symmetry_plane)
    skin_binding = _zero_offset_binding(build_topology_skin_binding(projected, skin_vertices, skin_triangles))
    guide_binding = build_topology_guide_binding(projected, quads, regions, face_guides, guides)
    validation = validate_warm_topology(vertices, quads, projected)
    reason = WarmInvalidationReason.NONE if validation.valid else WarmInvalidationReason.VALIDATION_FAILED
    status = WarmUpdateStatus(validation.valid, "Rebound", 1.0, validation.message, reason)
    return projected, skin_binding, guide_binding, status, validation


def enforce_symmetry(reference, vertices, plane):
    if plane is None or not len(vertices):
        return np.asarray(vertices)
    origin, normal = np.asarray(plane.origin), np.asarray(plane.normal, dtype=float)
    normal /= max(float(np.linalg.norm(normal)), 1e-12)
    reflected = _reflect(np.asarray(reference), origin, normal)
    distance, pairs = cKDTree(np.asarray(reference)).query(reflected)
    return _apply_symmetry(np.asarray(reference), np.asarray(vertices), pairs, distance, origin, normal)


def _apply_symmetry(reference, vertices, pairs, distance, origin, normal):
    output = np.asarray(vertices, dtype=float).copy(); scale = max(float(np.ptp(reference, axis=0).max()), 1.0)
    valid = (distance <= 1e-6 * scale) & (pairs[pairs] == np.arange(len(pairs)))
    indices = np.flatnonzero(valid & (np.arange(len(pairs)) <= pairs))
    for first in indices:
        _symmetry_pair(output, int(first), int(pairs[first]), origin, normal)
    return output


def _symmetry_pair(vertices, first, second, origin, normal):
    if first == second:
        vertices[first] -= np.dot(vertices[first] - origin, normal) * normal; return
    average = 0.5 * (vertices[first] + _reflect(vertices[second][None, :], origin, normal)[0])
    vertices[first], vertices[second] = average, _reflect(average[None, :], origin, normal)[0]


def _reflect(points, origin, normal):
    return points - 2.0 * np.sum((points - origin) * normal, axis=1)[:, None] * normal


def _zero_offset_binding(binding):
    from .model import TopologySkinBinding
    return TopologySkinBinding(binding.triangle_indices, binding.barycentric,
                               np.zeros_like(binding.offsets), binding.schema)


def validate_warm_topology(reference, quads, vertices):
    finite = bool(np.isfinite(vertices).all())
    no_inversions = _quad_orientation(reference, vertices, quads)
    displacement = np.linalg.norm(np.asarray(vertices) - reference, axis=1)
    valid = finite and no_inversions
    message = "Warm topology valid." if valid else "Warm topology contains invalid or inverted faces."
    return WarmValidationReport(valid, finite, no_inversions, True, 1.0,
                                float(np.quantile(displacement, 0.95)), message)


def _relax_project(reference, quads, targets, skin_vertices, skin_triangles, binding, iterations, guides):
    current = np.asarray(targets)
    key = f"topology:{structural_signature(len(reference), quads)}"
    locked = (guides.guide_indices >= 0) & (guides.rows >= 0)
    for _index in range(int(iterations)):
        proposal = constrained_arap(reference, _triangulate(quads), current, key, 1, 12.0)
        proposal = _project_bound_points(proposal, skin_vertices, skin_triangles, binding)
        proposal[locked] = targets[locked]
        current = proposal if _quad_orientation(reference, proposal, quads) else current
    return current


def _guide_prediction(vertices, binding, old_guides, new_guides):
    output = np.asarray(vertices, dtype=np.float64).copy()
    old_map, new_map = _guide_maps(old_guides), _guide_maps(new_guides)
    for index in set(binding.guide_indices.tolist()) - {-1}:
        mask = binding.guide_indices == index
        if index in old_map and index in new_map:
            output[mask] += _guide_delta(binding.parameters[mask], old_map[index], new_map[index])
    return output


def _guide_maps(guides):
    return {int(item.guide_index): np.asarray(item.points) for item in guides}


def _guide_delta(parameters, old_points, new_points):
    old = _sample_loop(old_points, parameters)
    new = _sample_loop(new_points, parameters)
    return new - old


def _sample_loop(points, parameters):
    position = np.mod(parameters, 1.0) * len(points)
    first = np.floor(position).astype(int) % len(points)
    second, blend = (first + 1) % len(points), position - np.floor(position)
    return points[first] * (1.0 - blend[:, None]) + points[second] * blend[:, None]


def _blend_constraints(surface, guided, binding):
    output = np.asarray(surface).copy()
    guide = binding.guide_indices >= 0
    transition = guide & (binding.rows < 0)
    output[guide] = guided[guide]
    output[transition] = 0.5 * (surface[transition] + guided[transition])
    return output


def _project_points(points, skin_vertices, skin_triangles):
    binding = build_topology_skin_binding(points, skin_vertices, skin_triangles)
    binding = _zero_offset_binding(binding)
    return evaluate_skin_binding(binding, skin_vertices, skin_triangles)


def _project_bound_points(points, skin_vertices, skin_triangles, binding):
    faces = np.asarray(skin_triangles, dtype=np.int32)[binding.triangle_indices]
    triangles = np.asarray(skin_vertices, dtype=np.float64)[faces]
    points = np.asarray(points, dtype=np.float64)
    projected, escaped = _project_rows(points, triangles)
    _PROJECTION_STATS["bound_vertices"] += len(points)
    if np.any(escaped):
        projected[escaped] = _fallback_projection(points[escaped], skin_vertices,
                                                   skin_triangles, binding, escaped)
    return projected


def _project_rows(points, triangles, chunk_size=32768):
    output, escaped = np.empty_like(points), np.zeros(len(points), dtype=bool)
    for start in range(0, len(points), int(chunk_size)):
        stop = min(len(points), start + int(chunk_size))
        output[start:stop], escaped[start:stop] = _project_chunk(points[start:stop], triangles[start:stop])
    return output, escaped


def _project_chunk(points, triangles):
    raw = _raw_row_barycentric(points, triangles)
    barycentric = np.maximum(raw, 0.0)
    barycentric /= np.maximum(barycentric.sum(axis=1, keepdims=True), 1e-12)
    projected = np.einsum("ni,nij->nj", barycentric, triangles)
    return projected, np.min(raw, axis=1) < -0.05


def _raw_row_barycentric(points, triangles):
    first = triangles[:, 0]
    u, v = triangles[:, 1] - first, triangles[:, 2] - first
    dot = lambda a, b: np.einsum("ij,ij->i", a, b)
    uu, uv, vv = dot(u, u), dot(u, v), dot(v, v)
    pu, pv = dot(points - first, u), dot(points - first, v)
    denominator = np.maximum(uu * vv - uv * uv, 1e-15)
    second = (pu * vv - pv * uv) / denominator
    third = (pv * uu - pu * uv) / denominator
    return np.column_stack((1.0 - second - third, second, third))


def _fallback_projection(points, skin_vertices, skin_triangles, binding, mask):
    rebound = build_topology_skin_binding(points, skin_vertices, skin_triangles)
    binding.triangle_indices[mask] = rebound.triangle_indices
    binding.barycentric[mask] = rebound.barycentric
    binding.offsets[mask] = 0.0
    _PROJECTION_STATS["global_fallback_vertices"] += len(points)
    return evaluate_skin_binding(rebound, skin_vertices, skin_triangles) - _offset_vectors(rebound, skin_vertices, skin_triangles)


def _offset_vectors(binding, vertices, faces):
    triangles = np.asarray(vertices)[np.asarray(faces)[binding.triangle_indices]]
    return _normals(triangles) * np.asarray(binding.offsets)[:, None]


def projection_stats():
    return dict(_PROJECTION_STATS)


def reset_projection_stats():
    _PROJECTION_STATS.update(bound_vertices=0, global_fallback_vertices=0)


def _triangulate(quads):
    values = np.asarray(quads, dtype=np.int32)
    return np.vstack((values[:, (0, 1, 2)], values[:, (0, 2, 3)]))


def _normals(triangles):
    values = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    return values / np.maximum(np.linalg.norm(values, axis=1, keepdims=True), 1e-12)


def _quad_orientation(reference, vertices, quads):
    old = _normals(np.asarray(reference)[_triangulate(quads)])
    new = _normals(np.asarray(vertices)[_triangulate(quads)])
    return bool(np.all(np.einsum("ij,ij->i", old, new) > 0.0))
