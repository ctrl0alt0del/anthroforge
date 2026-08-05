import numpy as np
from collections import OrderedDict
from scipy.sparse import coo_matrix, eye
from scipy.sparse.linalg import factorized

_FACTORIZATIONS = OrderedDict()
_EDGE_CACHE = OrderedDict()
_CACHE_STATS = {"edge_hits": 0, "factor_hits": 0, "factor_builds": 0}


def constrained_arap(reference, triangles, targets, cache_key, iterations=6, strength=8.0):
    edges = _cached_edges(triangles, cache_key)
    solve = _factorization(len(reference), edges, cache_key, strength)
    current = np.asarray(targets, dtype=np.float64).copy()
    for _index in range(int(iterations)):
        previous = current
        rotations = _rotations(reference, current, edges)
        rhs = _arap_rhs(reference, edges, rotations) + strength * targets
        current = np.column_stack([solve(rhs[:, axis]) for axis in range(3)])
        if _converged(previous, current):
            break
    return current.astype(np.float32)


def clear_arap_cache():
    _FACTORIZATIONS.clear()
    _EDGE_CACHE.clear()


def arap_cache_stats():
    return dict(_CACHE_STATS, edges=len(_EDGE_CACHE), factorizations=len(_FACTORIZATIONS))


def _cached_edges(triangles, key):
    cache_key = str(key)
    if cache_key in _EDGE_CACHE:
        _CACHE_STATS["edge_hits"] += 1
        _EDGE_CACHE.move_to_end(cache_key); return _EDGE_CACHE[cache_key]
    _EDGE_CACHE[cache_key] = _edges(triangles)
    _trim_cache(_EDGE_CACHE, 16)
    return _EDGE_CACHE[cache_key]


def _converged(previous, current, tolerance=1e-5):
    scale = max(float(np.linalg.norm(current, axis=1).mean()), 1.0)
    change = np.linalg.norm(current - previous, axis=1)
    return bool(float(change.max(initial=0.0)) <= tolerance * scale)


def _edges(triangles):
    faces = np.asarray(triangles, dtype=np.int32)
    values = np.vstack((faces[:, :2], faces[:, 1:], faces[:, ::2]))
    return np.unique(np.sort(values, axis=1), axis=0)


def _factorization(count, edges, key, strength):
    cache_key = (str(key), int(count), float(strength))
    if cache_key in _FACTORIZATIONS:
        _CACHE_STATS["factor_hits"] += 1
        _FACTORIZATIONS.move_to_end(cache_key); return _FACTORIZATIONS[cache_key]
    laplacian = _laplacian(count, edges)
    _FACTORIZATIONS[cache_key] = factorized((laplacian + strength * eye(count)).tocsc())
    _CACHE_STATS["factor_builds"] += 1
    _trim_cache(_FACTORIZATIONS, 8)
    return _FACTORIZATIONS[cache_key]


def _trim_cache(cache, limit):
    while len(cache) > int(limit):
        cache.popitem(last=False)


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
