import numpy as np
from scipy.spatial import cKDTree

from .topology_solver import _normals, _sample_loop, _triangulate


def surface_deviation(first, second):
    first, second = np.asarray(first), np.asarray(second)
    if not len(first) or not len(second):
        return {"mean": float("inf"), "p95": float("inf"), "max": float("inf")}
    distances = np.concatenate((cKDTree(first).query(second)[0], cKDTree(second).query(first)[0]))
    return {"mean": float(distances.mean()), "p95": float(np.quantile(distances, 0.95)),
            "max": float(distances.max())}


def inversion_count(reference, vertices, quads):
    faces = _triangulate(quads)
    old = _normals(np.asarray(reference)[faces])
    new = _normals(np.asarray(vertices)[faces])
    return int(np.count_nonzero(np.einsum("ij,ij->i", old, new) <= 0.0))


def guide_error(vertices, binding, guides):
    guide_map = {int(item.guide_index): np.asarray(item.points) for item in guides}
    errors = [_guide_distances(vertices, binding, index, points)
              for index, points in guide_map.items()]
    values = np.concatenate([item for item in errors if len(item)]) if any(map(len, errors)) else np.zeros(1)
    return {"mean": float(values.mean()), "max": float(values.max())}


def _guide_distances(vertices, binding, index, points):
    mask = (binding.guide_indices == index) & (binding.rows >= 0)
    expected = _sample_loop(points, binding.parameters[mask])
    return np.linalg.norm(np.asarray(vertices)[mask] - expected, axis=1)


def symmetry_error(vertices, origin, normal):
    points = np.asarray(vertices); origin, normal = np.asarray(origin), np.asarray(normal)
    normal = normal / max(float(np.linalg.norm(normal)), 1e-12)
    reflected = points - 2.0 * np.sum((points - origin) * normal, axis=1)[:, None] * normal
    distances = cKDTree(points).query(reflected)[0]
    return {"mean": float(distances.mean()), "max": float(distances.max())}
