"""Adopted barycentric patches follow compatible topology; remeshing requires rebinding."""
import numpy as np
from .errors import require
from . import clipping, substrate, visual_mesh, visual_selection
from .indexed_patches import resolve


def partition(polygons, query, chart, budget):
    patches = resolve(chart['geometry'], query)
    visual_selection.world_polygons(chart['geometry'], patches)
    triangles = substrate.surface(chart)
    masks = {}
    for row in patches:
        masks.setdefault(row['triangle'], []).append(np.asarray(row['polygon'])[:, [1, 2, 0]])
    inside, outside = [], []
    for index, coordinates in correspondences(triangles, polygons, budget):
        a, b = cut(coordinates, masks.get(index, []), budget)
        inside.extend(p[:, [2, 0, 1]] @ triangles[index] for p in a)
        outside.extend(p[:, [2, 0, 1]] @ triangles[index] for p in b)
    return inside, outside


def correspondences(triangles, polygons, budget):
    aligned = len(polygons) == len(triangles) and all(np.array_equal(p, t) for p, t in zip(polygons, triangles))
    identity = np.eye(3)[:, [1, 2, 0]]
    for index, polygon in enumerate(polygons):
        budget.check()
        yield (index, identity) if aligned else locate(triangles, polygon)


def locate(triangles, polygon):
    low, high = np.min(polygon, axis=0), np.max(polygon, axis=0)
    candidates = np.flatnonzero(np.all(triangles.min(1) <= low+1e-7, axis=1) & np.all(triangles.max(1) >= high-1e-7, axis=1))
    for index in candidates:
        weights = visual_mesh.barycentric(triangles[index], polygon)
        if weights.min() >= -1e-7 and np.allclose(weights @ triangles[index], polygon, atol=1e-7, rtol=0):
            return int(index), weights[:, [1, 2, 0]]
    require(False, 'SURFACE_PATCH_CORRESPONDENCE_INVALID')


def cut(polygon, masks, budget):
    inside, outside = [], [polygon]
    for mask in masks:
        selected, outside = clipping.partition(outside, visual_selection.planes(mask), budget)
        inside.extend(selected)
    return inside, outside
