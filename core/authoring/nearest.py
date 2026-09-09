"""Closest-point inspection helper; authoring ray constraints remain authoritative."""
import numpy as np
from .geometry import normalized


def segment(point, a, b):
    edge = b-a
    size = np.einsum("ij,ij->i", edge, edge)
    t = np.divide(np.einsum("ij,ij->i", point-a, edge), size, out=np.zeros_like(size), where=size > 1e-24)
    return a + np.clip(t, 0, 1)[:, None]*edge


def on_triangles(tris, point):
    a, b, c = tris[:,0], tris[:,1], tris[:,2]
    normal = normalized(np.cross(b-a, c-a))
    projection = point-np.einsum("ij,ij->i", point-a, normal)[:,None]*normal
    inside = np.ones(len(tris), dtype=bool)
    for x, y in ((a,b),(b,c),(c,a)):
        inside &= np.einsum("ij,ij->i", np.cross(y-x, projection-x), normal) >= 0
    edges = np.stack([segment(point,x,y) for x,y in ((a,b),(b,c),(c,a))], axis=1)
    closest = edges[np.arange(len(tris)), np.argmin(np.linalg.norm(edges-point, axis=2), axis=1)]
    return np.where(inside[:,None], projection, closest)


def nearest(tris, point):
    candidates = on_triangles(tris, point)
    index = int(np.argmin(np.linalg.norm(candidates-point, axis=1)))
    return candidates[index], index
