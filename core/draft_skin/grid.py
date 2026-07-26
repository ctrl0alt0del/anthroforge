import numpy as np

from .constants import MIN_RESOLUTION, PADDING_VOXELS, TARGET_RESOLUTION


def grid_spec(vertices, resolution=TARGET_RESOLUTION):
    lower, upper = vertices.min(axis=0), vertices.max(axis=0)
    length = float(np.max(upper - lower))
    voxel = length / max(1, int(resolution))
    padding = PADDING_VOXELS * voxel
    origin = lower - padding
    dimensions = np.ceil((upper - lower + (2.0 * padding)) / voxel).astype(np.int32) + 1
    return origin, tuple(int(value) for value in dimensions), voxel


def estimated_bytes(dimensions):
    return int(np.prod(dimensions, dtype=np.int64)) * 104


def choose_resolution(vertices, memory_limit, target=TARGET_RESOLUTION):
    resolution = max(16, int(target))
    minimum = min(MIN_RESOLUTION, resolution)
    while resolution > minimum:
        spec = grid_spec(vertices, resolution)
        if estimated_bytes(spec[1]) <= int(memory_limit):
            return resolution, spec
        resolution -= 10
    spec = grid_spec(vertices, minimum)
    return minimum, spec
