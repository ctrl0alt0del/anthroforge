"""Validate saved update bindings before any numerical deformation work."""
import numpy as np


def valid_skin_binding(binding, sources, count):
    if binding is None:
        return False
    try:
        return (_shapes(binding, count) and _values(binding)
                and _references(binding, sources))
    except (AttributeError, TypeError, ValueError, IndexError):
        return False


def _shapes(binding, count):
    shape = np.shape(binding.weights)
    return (len(shape) == 2 and shape[0] == count and shape[1] > 0
            and np.shape(binding.source_indices) == shape
            and np.shape(binding.triangle_indices) == shape
            and np.shape(binding.barycentric) == (*shape, 3)
            and np.shape(binding.normal_offsets) == (count,))


def _values(binding):
    weights = np.asarray(binding.weights)
    barycentric = np.asarray(binding.barycentric)[weights > 0]
    return (np.isfinite(weights).all() and (weights >= 0).all()
            and np.allclose(weights.sum(axis=1), 1.0, atol=1e-5)
            and np.isfinite(binding.normal_offsets).all()
            and np.isfinite(barycentric).all() and (barycentric >= -1e-5).all()
            and np.allclose(barycentric.sum(axis=1), 1.0, atol=1e-5))


def _references(binding, sources):
    ids, triangles = np.asarray(binding.source_indices), np.asarray(binding.triangle_indices)
    if ids.dtype.kind not in 'iu' or triangles.dtype.kind not in 'iu':
        return False
    active = np.asarray(binding.weights) > 0
    known = np.zeros(ids.shape, dtype=bool)
    for source in sources:
        mask = active & (ids == int(source.source_index))
        if np.any((triangles[mask] < 0) | (triangles[mask] >= len(source.triangles))):
            return False
        known |= mask
    return bool(np.all(known[active]))
