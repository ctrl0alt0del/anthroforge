"""Explicit bone-frame mapping with batched native projection onto a region."""
import numpy as np
from .errors import require
from ..vcp.v2.collision_native import NativeCollisionWorld


def frame(value):
    p = np.asarray(value, dtype=float)
    require(p.shape == (3, 3) and np.isfinite(p).all(), 'TRANSFER_BAND_FRAME')
    axis = p[1]-p[0]; length = float(np.linalg.norm(axis))
    require(length > 1e-12, 'TRANSFER_BAND_FRAME')
    axis /= length; side = p[2]-p[0]; side -= axis*float(side@axis)
    require(np.linalg.norm(side) > length*1e-8, 'TRANSFER_BAND_FRAME')
    side /= np.linalg.norm(side)
    return p[0], np.asarray([axis, side, np.cross(axis, side)]), length


def guesses(vertices, mapping):
    origin, axes, length = frame(mapping['source_frame'])
    destination, target_axes, target_length = frame(mapping['target_frame'])
    return (np.asarray(vertices)-origin)@axes.T@target_axes*(target_length/length)+destination


def region_mesh(polygons):
    vertices, faces = [], []
    for polygon in polygons:
        begin = len(vertices); vertices.extend(polygon)
        faces.extend([begin, begin+i, begin+i+1] for i in range(1, len(polygon)-1))
    require(bool(faces), 'TRANSFER_REGION_EMPTY')
    return np.asarray(vertices, float), np.asarray(faces, np.int64)


def project(vertices, polygons, mapping):
    points = guesses(vertices, mapping); mesh, faces = region_mesh(polygons)
    world, _closed = NativeCollisionWorld.from_batch([mesh], [faces], [0])
    try:
        nearest, _normals, _distances, owners, _inside = world.nearest(points)
    finally:
        world.close()
    distance = np.linalg.norm(nearest-points, axis=1)
    require(np.isfinite(nearest).all() and (owners >= 0).all(), 'TRANSFER_BAND_PROJECTION')
    require(float(distance.max()) <= mapping['max_distance'], 'TRANSFER_BAND_PROJECTION_DISTANCE',
            'Mapped band exceeds its explicit projection budget; inspect frames and region.')
    return nearest, dict(method='bone_frame_nearest_region.v1', max_projection_distance=float(distance.max()))
