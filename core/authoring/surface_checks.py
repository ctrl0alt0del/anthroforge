"""Reject locally folded or collapsed inflated patches before publication."""
import numpy as np
from .errors import require
from .geometry import ray_hits
from .inflation import faces


def check(base, inflated, closed):
    first, second = triangle_normals(inflated, closed)
    lengths = np.linalg.norm(first, axis=-1) + np.linalg.norm(second, axis=-1)
    require(bool(np.all(lengths > 1e-20)), "SURFACE_COLLAPSED")
    quads = faces(len(inflated), len(inflated[0]), closed)
    indices = np.vstack((quads[:,:3], quads[:,[0,2,3]]))
    pairs = intersections(inflated.reshape(-1,3), indices)
    require(not pairs, "INFLATED_SELF_INTERSECTION", str(pairs[:8]))


def triangle_normals(grid, closed):
    values = np.concatenate((grid, grid[:, :1]), axis=1) if closed else grid
    a, b, c, d = values[:-1, :-1], values[1:, :-1], values[1:, 1:], values[:-1, 1:]
    return np.cross(b-a, c-a), np.cross(c-a, d-a)


def intersections(vertices, indices):
    triangles = np.asarray(vertices)[indices]
    _, weld = np.unique(np.round(vertices,10), axis=0, return_inverse=True)
    low, high = triangles.min(axis=1), triangles.max(axis=1)
    pairs = []
    for index, tri in enumerate(triangles):
        candidates = np.flatnonzero(np.all(high >= low[index]-1e-9, axis=1) & np.all(low <= high[index]+1e-9, axis=1))
        for other in candidates[candidates > index]:
            if np.any(weld[indices[index,:,None]] == weld[indices[other,None,:]]):
                continue
            if crossing(tri, triangles[other]):
                pairs.append((int(index), int(other)))
                if len(pairs) >= 32:
                    return pairs
    return pairs


def crossing(first, second):
    for source, target in ((first, second), (second, first)):
        for a,b in ((0,1),(1,2),(2,0)):
            delta = source[b]-source[a]
            length = np.linalg.norm(delta)
            if length > 1e-12 and ray_hits(target[None], source[a], delta/length, length):
                return True
    return coplanar_overlap(first, second)


def coplanar_overlap(first, second):
    normal = np.cross(first[1]-first[0], first[2]-first[0])
    size = np.linalg.norm(normal)
    if size < 1e-12 or np.max(np.abs((second-first[0]) @ normal)) > 1e-10*size:
        return False
    axes = [i for i in range(3) if i != np.argmax(abs(normal))]
    a, b = first[:,axes], second[:,axes]
    for polygon in (a, b):
        for edge in np.roll(polygon,-1,axis=0)-polygon:
            axis = np.array([-edge[1],edge[0]])
            x, y = a @ axis, b @ axis
            if min(x.max(),y.max()) <= max(x.min(),y.min())+1e-12:
                return False
    return True
