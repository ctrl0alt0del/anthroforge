import numpy as np
from scipy.spatial import cKDTree

from ..warm_start.model import SkinWarmBinding


def build_skin_bindings(vertices, sources, influences=4):
    triangles, source_ids, local_ids = _source_triangles(sources)
    if not len(triangles):
        return empty_skin_bindings(len(vertices), influences), _quality(1.0, 0.0, 1.0)
    centroids = triangles.mean(axis=1)
    candidates = _candidate_indices(cKDTree(centroids), vertices, len(triangles))
    binding = _bind_vertices(np.asarray(vertices), triangles, candidates,
                             source_ids, local_ids, influences)
    return binding, binding_quality(binding)


def empty_skin_bindings(count, influences=4):
    shape = (int(count), int(influences))
    return SkinWarmBinding(np.full(shape, -1, np.int32), np.full(shape, -1, np.int32),
                           np.zeros((*shape, 3), np.float32), np.zeros(shape, np.float32),
                           np.zeros(count, np.float32), np.zeros(count, np.float32))


def binding_quality(binding):
    weights = np.asarray(binding.weights)
    unbound = float(np.mean(weights.sum(axis=1) <= 0.0)) if len(weights) else 1.0
    ordered = np.sort(weights, axis=1) if len(weights) else np.empty((0, 4))
    ambiguous = float(np.mean(ordered[:, -2] >= 0.9 * ordered[:, -1])) if len(weights) else 0.0
    invisible = float(np.mean(np.asarray(binding.support) < 0.25)) if len(weights) else 1.0
    return _quality(unbound, ambiguous, invisible)


def _quality(unbound, ambiguous, invisible):
    return {"unbound_percent": 100.0 * unbound,
            "ambiguous_percent": 100.0 * ambiguous,
            "visibility_rejected_percent": 100.0 * invisible,
            "binding_schema": 1}


def _source_triangles(sources):
    blocks, source_ids, local_ids = [], [], []
    for source in sources:
        faces = np.asarray(source.triangles, dtype=np.int32)
        blocks.append(np.asarray(source.vertices, dtype=np.float64)[faces])
        source_ids.extend([int(source.source_index)] * len(faces))
        local_ids.extend(range(len(faces)))
    triangles = np.concatenate(blocks) if blocks else np.empty((0, 3, 3))
    return triangles, np.asarray(source_ids, np.int32), np.asarray(local_ids, np.int32)


def _candidate_indices(tree, vertices, triangle_count):
    count = min(24, int(triangle_count))
    _distances, indices = tree.query(np.asarray(vertices), k=count)
    return np.asarray(indices, dtype=np.int32).reshape(len(vertices), count)


def _bind_vertices(vertices, triangles, candidates, source_ids, local_ids, influences):
    result = empty_skin_bindings(len(vertices), influences)
    arrays = [np.array(value, copy=True) for value in _binding_arrays(result)]
    for index, point in enumerate(vertices):
        _bind_one(index, point, triangles, candidates[index], source_ids,
                  local_ids, arrays, influences)
    return SkinWarmBinding(*arrays, schema=1)


def _binding_arrays(binding):
    return (binding.source_indices, binding.triangle_indices, binding.barycentric,
            binding.weights, binding.normal_offsets, binding.support)


def _bind_one(index, point, triangles, candidates, source_ids, local_ids, arrays, influences):
    barycentric, projected = _project_candidates(point, triangles[candidates])
    distances = np.linalg.norm(projected - point, axis=1)
    preferred = _source_order(distances, source_ids[candidates], influences)
    chosen, visible = _visible_order(point, projected, triangles[candidates], preferred)
    selected, values = candidates[chosen], distances[chosen]
    weights = _distance_weights(values)
    _store_binding(index, point, triangles[selected], source_ids[selected],
                   local_ids[selected], barycentric[chosen], weights, arrays, visible)


def _source_order(distances, sources, influences):
    chosen, seen = [], set()
    for index in np.argsort(distances):
        source = int(sources[index])
        if source not in seen:
            chosen.append(int(index)); seen.add(source)
        if len(chosen) == influences:
            break
    return np.asarray(chosen, dtype=np.int32)


def _visible_order(point, projected, triangles, chosen):
    if len(chosen) <= 1:
        return chosen, np.ones(len(chosen), dtype=bool)
    visible = _candidate_visibility(point, projected[chosen], triangles)
    accepted = chosen[visible]
    if len(accepted):
        return accepted, np.ones(len(accepted), dtype=bool)
    return chosen[:1], np.zeros(1, dtype=bool)


def _candidate_visibility(point, projected, triangles):
    return np.asarray([not _segment_occluded(point, target, triangles)
                       for target in projected], dtype=bool)


def _segment_occluded(point, target, triangles):
    direction = np.asarray(target) - np.asarray(point)
    edge1 = triangles[:, 1] - triangles[:, 0]
    edge2 = triangles[:, 2] - triangles[:, 0]
    cross = np.cross(np.broadcast_to(direction, edge2.shape), edge2)
    determinant = np.einsum("ij,ij->i", edge1, cross)
    return _has_segment_hit(point, direction, triangles, edge1, edge2, cross, determinant)


def _has_segment_hit(point, direction, triangles, edge1, edge2, cross, determinant):
    valid = np.abs(determinant) > 1e-12
    inverse = np.zeros_like(determinant)
    np.divide(1.0, determinant, out=inverse, where=valid)
    delta = np.asarray(point) - triangles[:, 0]
    u = inverse * np.einsum("ij,ij->i", delta, cross)
    q = np.cross(delta, edge1)
    v = inverse * np.einsum("j,ij->i", direction, q)
    t = inverse * np.einsum("ij,ij->i", edge2, q)
    hit = valid & (u >= -1e-8) & (v >= -1e-8) & (u + v <= 1.0 + 1e-8)
    return bool(np.any(hit & (t > 1e-7) & (t < 1.0 - 1e-6)))


def _project_candidates(point, triangles):
    first, u, v = triangles[:, 0], triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    rhs = np.column_stack((np.einsum("ij,ij->i", point - first, u),
                           np.einsum("ij,ij->i", point - first, v)))
    matrix = np.stack((np.sum(u * u, 1), np.sum(u * v, 1),
                       np.sum(u * v, 1), np.sum(v * v, 1)), axis=1).reshape(-1, 2, 2)
    uv = _safe_solve(matrix, rhs)
    barycentric = _clamped_barycentric(uv)
    return barycentric, np.einsum("ni,nij->nj", barycentric, triangles)


def _safe_solve(matrix, rhs):
    determinant = np.linalg.det(matrix)
    valid = np.abs(determinant) > 1e-15
    result = np.zeros_like(rhs)
    result[valid] = np.linalg.solve(matrix[valid], rhs[valid])
    return result


def _clamped_barycentric(uv):
    values = np.column_stack((1.0 - uv.sum(axis=1), uv))
    values = np.maximum(values, 0.0)
    return values / np.maximum(values.sum(axis=1, keepdims=True), 1e-12)


def _distance_weights(distances):
    inverse = 1.0 / np.maximum(np.asarray(distances), 1e-9)
    return inverse / inverse.sum()


def _store_binding(index, point, triangles, sources, local, barycentric, weights, arrays, visible):
    source_out, triangle_out, bary_out, weight_out, offset_out, support_out = arrays
    projected = np.einsum("ni,nij->nj", barycentric, triangles)
    normals = _triangle_normals(triangles)
    count = len(sources)
    source_out[index, :count], triangle_out[index, :count] = sources, local
    bary_out[index, :count], weight_out[index, :count] = barycentric, weights
    offset_out[index] = float(np.sum(weights * np.einsum("ij,ij->i", point - projected, normals)))
    support_out[index] = float(np.sum(weights * visible))


def _triangle_normals(triangles):
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    return normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)


def _visibility(point, projected, normals):
    delta = point - projected
    length = np.linalg.norm(delta, axis=1)
    cosine = np.abs(np.einsum("ij,ij->i", delta, normals)) / np.maximum(length, 1e-12)
    return np.where(length <= 1e-10, 1.0, cosine)
