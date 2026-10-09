"""Area-weighted normals suppress float32 sliver noise on regenerated lofts."""
import numpy as np


def normals(points, faces):
    vertices = np.asarray(points, dtype=np.float64); accumulated = np.zeros_like(vertices)
    for face in faces:
        ids = np.asarray(face, dtype=np.int64); polygon = vertices[ids] - vertices[ids[0]]
        area = np.cross(polygon, np.roll(polygon, -1, axis=0)).sum(axis=0)
        accumulated[ids] += area
    lengths = np.linalg.norm(accumulated, axis=1)
    if np.any(lengths <= 1e-12): raise ValueError('Source surface has a degenerate normal frame.')
    return tuple(map(tuple, accumulated / lengths[:, None]))
