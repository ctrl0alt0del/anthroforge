"""Calibrated orthographic cameras; normalized image coordinates start at top left."""
import numpy as np
from .errors import require
from .geometry import normalized

DIRECTIONS = {'+X': [1, 0, 0], '-X': [-1, 0, 0], '+Y': [0, 1, 0], '-Y': [0, -1, 0], '+Z': [0, 0, 1], '-Z': [0, 0, -1], 'OBLIQUE_A': [1, -1, 1], 'OBLIQUE_B': [-1, 1, 1]}


def vertices(geometry):
    matrix = np.asarray(geometry['matrix'], dtype=float)
    return np.asarray(geometry['vertices']) @ matrix[:3, :3].T + matrix[:3, 3]


def make(geometry, direction, size=512, center=None, span=None):
    points = vertices(geometry)
    require(len(points) > 2, 'SURFACE_DOMAIN_UNAVAILABLE')
    center = (points.min(0)+points.max(0))/2 if center is None else np.asarray(center)
    span = float(np.linalg.norm(points.max(0)-points.min(0))*1.15) if span is None else float(span)
    require(span > 1e-10 and 64 <= size <= 1024, 'VIEW_CAMERA_INVALID')
    matrix = orientation(geometry)
    forward = -normalized(matrix @ normalized(direction))
    hint = normalized(matrix @ [0, 0, 1])
    hint = normalized(matrix @ [0, 1, 0]) if abs(hint @ forward) > .95 else hint
    right = normalized(np.cross(forward, hint))
    up = normalized(np.cross(right, forward))
    return dict(projection='orthographic', center=center.tolist(), right=right.tolist(), up=up.tolist(), forward=forward.tolist(), span=span, width=size, height=size, coordinates='normalized_top_left', pixel_centers='(x+0.5)/width,(y+0.5)/height')


def project(camera, points):
    points = np.asarray(points)-camera['center']
    return np.stack([.5+points @ camera['right']/camera['span'], .5-points @ camera['up']/camera['span'], points @ camera['forward']], axis=-1)


def unproject(camera, points):
    points = np.asarray(points)
    return camera['center']+(points[..., 0:1]-.5)*camera['span']*np.asarray(camera['right'])-(points[..., 1:2]-.5)*camera['span']*np.asarray(camera['up'])+points[..., 2:3]*np.asarray(camera['forward'])


def ray(camera, uv, triangles):
    require(len(uv) == 2 and np.all(np.isfinite(uv)) and min(uv) >= 0 and max(uv) <= 1, 'VIEW_COORDINATE_INVALID')
    depths = project(camera, triangles.reshape((-1, 3)))[:, 2]
    origin = unproject(camera, np.array([*uv, depths.min()-camera['span']]))
    return origin, np.asarray(camera['forward']), float(np.ptp(depths)+2*camera['span'])


def orbit(geometry, source, params):
    old = normalized(orientation(geometry).T @ -np.asarray(source['forward']))
    previous = np.degrees([np.arctan2(old[1], old[0]), np.arcsin(np.clip(old[2], -1, 1))])
    azimuth, elevation = np.radians([params.get('azimuth', previous[0]), params.get('elevation', previous[1])])
    direction = [np.cos(elevation)*np.cos(azimuth), np.cos(elevation)*np.sin(azimuth), np.sin(elevation)]
    zoom = params.get('zoom', 1.)
    require(.1 <= zoom <= 20, 'VIEW_ZOOM_INVALID')
    return make(geometry, direction, source['width'], params.get('center', source['center']), source['span']/zoom)


def orientation(geometry):
    matrix = np.asarray(geometry['matrix'])[:3, :3]
    require(abs(float(np.linalg.det(matrix))) > 1e-12, 'VIEW_TRANSFORM_DEGENERATE')
    left, _, right = np.linalg.svd(matrix)
    return left @ right
