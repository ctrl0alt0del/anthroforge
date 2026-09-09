"""Native distributed-inflation stability limiter on material grids."""
import numpy as np


def limit(grid, normals, amount, closed):
    stability = np.ones(grid.shape[:2])
    radius = np.full(grid.shape[:2], np.inf)
    for axis in (0,1):
        for step in (-1,1):
            neighbor = np.roll(normals, step, axis=axis)
            distance = np.linalg.norm(grid-np.roll(grid, step, axis=axis), axis=2)
            dots = np.maximum(0, np.einsum("ijk,ijk->ij", normals, neighbor))
            clear_edge(dots, distance, axis, step, closed)
            stability = np.minimum(stability, dots)
            radius = np.minimum(radius, distance)
    weight = np.clip(stability/.85, 0, 1)
    clamped = np.minimum(amount, radius*2.5)
    return clamped + (amount-clamped)*weight


def clear_edge(dots, distance, axis, step, closed):
    if axis == 1 and closed:
        return
    index = [slice(None), slice(None)]
    index[axis] = 0 if step == 1 else -1
    dots[tuple(index)] = 1
    distance[tuple(index)] = np.inf
