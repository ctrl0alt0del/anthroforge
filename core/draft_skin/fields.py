import numpy as np
from scipy import ndimage

from .constants import COLLAGEN_LEVELS, TARGET_RESOLUTION
from .settings import DEFAULT_SETTINGS, resolved_distances
from .status import check_cancelled


def surface_distance(surface, voxel):
    return ndimage.distance_transform_edt(~surface, sampling=float(voxel))


def exterior_field(distance, voxel, probe_distance, offset_distance):
    free = distance > (float(probe_distance) + float(offset_distance))
    labels, _count = ndimage.label(free, structure=np.ones((3, 3, 3), dtype=bool))
    outside = labels == labels[(0, 0, 0)]
    reach = ndimage.distance_transform_edt(~outside, sampling=float(voxel))
    return reach - float(probe_distance)


def smooth_max(first, second, radius):
    if radius <= 0.0:
        return np.maximum(first, second)
    weight = np.clip(0.5 + (0.5 * (first - second) / radius), 0.0, 1.0)
    return second * (1.0 - weight) + first * weight + radius * weight * (1.0 - weight)


def collagen_field(surface, seeds, voxel, inner=None, outer=None, progress=None, cancelled=None):
    quantized, seeded = _quantized_seeds(seeds)
    levels = tuple(value for value in np.unique(quantized[seeded]) if value < 1.0)
    collagen = np.ones(surface.shape, dtype=np.float64)
    inner, outer = _falloff_bounds(voxel, inner, outer)
    for index, value in enumerate(levels):
        check_cancelled(cancelled)
        mask = ndimage.binary_dilation(seeded & np.isclose(quantized, value), iterations=1)
        distance = surface_distance(mask, voxel)
        collagen = np.minimum(collagen, _collagen_falloff(distance, inner, outer, float(value)))
        _notify(progress, index + 1, len(levels))
    return collagen


def _quantized_seeds(seeds):
    seeded = np.isfinite(seeds)
    values = np.where(seeded, np.minimum(seeds, 1.0), 1.0)
    scale = float(COLLAGEN_LEVELS - 1)
    return np.round(np.clip(values, 0.0, 1.0) * scale) / scale, seeded


def _falloff_bounds(voxel, inner, outer):
    defaults = resolved_distances(DEFAULT_SETTINGS, TARGET_RESOLUTION * float(voxel))
    return defaults[2] if inner is None else float(inner), defaults[3] if outer is None else float(outer)


def _collagen_falloff(distance, inner, outer, minimum):
    width = float(outer) - float(inner)
    factor = (distance > inner).astype(np.float64) if width <= 0.0 else np.clip((distance - inner) / width, 0.0, 1.0)
    factor = factor * factor * (3.0 - (2.0 * factor))
    return minimum + ((1.0 - minimum) * factor)


def _notify(progress, current, total):
    if progress:
        progress(float(current) / max(1, int(total)))
