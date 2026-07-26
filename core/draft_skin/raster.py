import math

import numpy as np
from scipy import ndimage

from .constants import RASTER_BATCH, RASTER_SAMPLE
from .status import check_cancelled


def barycentric_weights(steps):
    indices = np.indices((steps + 1, steps + 1)).reshape(2, -1).T
    uv = indices[indices.sum(axis=1) <= steps].astype(np.float64) / steps
    return np.column_stack((1.0 - uv.sum(axis=1), uv))


def sampling_steps(triangles, voxel):
    edges = triangles[:, [1, 2, 0]] - triangles
    lengths = np.linalg.norm(edges, axis=2).max(axis=1)
    return np.maximum(1, np.ceil(lengths / (RASTER_SAMPLE * voxel)).astype(np.int32))


def rasterize(vertices, faces, origin, dimensions, voxel, values=None, progress=None, cancelled=None):
    face_indices = np.asarray(faces, dtype=np.int32)
    triangles = np.asarray(vertices, dtype=np.float64)[face_indices]
    triangle_values = None if values is None else np.asarray(values, dtype=np.float32)[face_indices]
    steps = sampling_steps(triangles, voxel)
    surface = np.zeros(dimensions, dtype=bool)
    seeds = _seed_grid(dimensions, values)
    groups = tuple(np.unique(steps))
    for group_index, step in enumerate(groups):
        _raster_group(triangles, steps, step, origin, voxel, surface, seeds, triangle_values, cancelled)
        _notify(progress, group_index + 1, len(groups))
    return _dilate(surface, seeds)


def _seed_grid(dimensions, values):
    return None if values is None else np.full(dimensions, np.inf, dtype=np.float32)


def _raster_group(triangles, steps, step, origin, voxel, surface, seeds, values, cancelled):
    indices = np.flatnonzero(steps == int(step))
    weights = barycentric_weights(int(step))
    for start in range(0, len(indices), RASTER_BATCH):
        check_cancelled(cancelled)
        batch = indices[start : start + RASTER_BATCH]
        points = np.einsum("wj,bjk->bwk", weights, triangles[batch], optimize=True)
        cells = np.rint((points - origin) / voxel).astype(np.int32)
        _write_cells(cells, surface, seeds, values, batch, weights)


def _write_cells(cells, surface, seeds, values, batch, weights):
    flat = np.ravel_multi_index(cells.reshape(-1, 3).T, surface.shape, mode="clip")
    surface.ravel()[flat] = True
    if seeds is None:
        return
    samples = np.einsum("wj,bj->bw", weights, values[batch], optimize=True)
    np.minimum.at(seeds.ravel(), flat, samples.reshape(-1).astype(np.float32))


def _dilate(surface, seeds):
    dilated = ndimage.binary_dilation(surface, iterations=1)
    if seeds is None:
        return dilated, None
    return dilated, seeds


def _notify(progress, current, total):
    if progress:
        progress(float(current) / max(1, int(total)))
