import numpy as np
from scipy.sparse import coo_matrix, eye
from scipy.sparse.linalg import factorized

_FACTORIZATIONS = {}


def constrained_arap(reference, triangles, targets, cache_key, iterations=6, strength=8.0):
    edges = _edges(triangles)
    solve = _factorization(len(reference), edges, cache_key, strength)
    current = np.asarray(targets, dtype=np.float64).copy()
    for _index in range(int(iterations)):
        rotations = _rotations(reference, current, edges)
        rhs = _arap_rhs(reference, edges, rotations) + strength * targets
        current = np.column_stack([solve(rhs[:, axis]) for axis in range(3)])
    return current.astype(np.float32)


def clear_arap_cache():
    _FACTORIZATIONS.clear()


def _edges(triangles):
    faces = np.asarray(triangles, dtype=np.int32)
    values = np.vstack((faces[:, :2], faces[:, 1:], faces[:, ::2]))
    return np.unique(np.sort(values, axis=1), axis=0)


def _factorization(count, edges, key, strength):
    cache_key = (str(key), int(count), float(strength))
    if cache_key not in _FACTORIZATIONS:
        laplacian = _laplacian(count, edges)
        _FACTORIZATIONS[cache_key] = factorized((laplacian + strength * eye(count)).tocsc())
    return _FACTORIZATIONS[cache_key]


def _laplacian(count, edges):
    rows = np.concatenate((edges[:, 0], edges[:, 1], edges[:, 0], edges[:, 1]))
    cols = np.concatenate((edges[:, 1], edges[:, 0], edges[:, 0], edges[:, 1]))
    data = np.concatenate((-np.ones(2 * len(edges)), np.ones(2 * len(edges))))
    return coo_matrix((data, (rows, cols)), shape=(count, count)).tocsr()


def _rotations(reference, current, edges):
    covariance = np.zeros((len(reference), 3, 3), dtype=np.float64)
    first, second = edges[:, 0], edges[:, 1]
    old, new = reference[first] - reference[second], current[first] - current[second]
    outer = np.einsum("ni,nj->nij", old, new)
    np.add.at(covariance, first, outer); np.add.at(covariance, second, outer)
    return _batch_rotations(covariance)


def _batch_rotations(covariance):
    left, _values, right = np.linalg.svd(covariance, full_matrices=False)
    rotations = right.transpose(0, 2, 1) @ left.transpose(0, 2, 1)
    flipped = np.linalg.det(rotations) < 0.0
    right[flipped, -1] *= -1.0
    return right.transpose(0, 2, 1) @ left.transpose(0, 2, 1)


def _rotation(covariance):
    left, _values, right = np.linalg.svd(covariance, full_matrices=False)
    rotation = right.T @ left.T
    if np.linalg.det(rotation) < 0.0:
        right[-1] *= -1.0; rotation = right.T @ left.T
    return rotation


def _arap_rhs(reference, edges, rotations):
    rhs = np.zeros_like(reference, dtype=np.float64)
    first, second = edges[:, 0], edges[:, 1]
    average = 0.5 * (rotations[first] + rotations[second])
    vector = np.einsum("nij,nj->ni", average, reference[first] - reference[second])
    np.add.at(rhs, first, vector); np.add.at(rhs, second, -vector)
    return rhs
