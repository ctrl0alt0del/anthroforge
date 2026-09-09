"""Depth-aware patch, wire and construction-control overlays."""
import numpy as np
from . import visual_camera as camera, visual_selection as selection, visual_raster as raster, clipping
from .visual_mesh import clipped


def patches(pixels, buffer, scene, view, rows):
    depth, ids = np.full(buffer['ids'].shape, np.inf), np.full(buffer['ids'].shape, -1, dtype=int)
    polygons = selection.world_polygons(scene['geometry'][scene['owner']], rows)
    for triangle in clipping.triangulate(polygons):
        for fragment in clipped(triangle, view.get('section')):
            raster.raster_triangle(camera.project(view['camera'], fragment), 0, depth, ids)
    visible = (ids >= 0) & (depth <= buffer['depth']+view['camera']['span']*1e-7)
    result = pixels.copy()
    result[visible] = (.3*result[visible]+.7*np.array([241, 159, 55])).astype(np.uint8)
    return result


def lines(pixels, depth, spec, paths, color):
    result = pixels.copy()
    for path in paths:
        projected = camera.project(spec, path)
        for first, last in zip(projected, projected[1:]):
            line(result, depth, spec, first, last, color)
    return result


def line(pixels, depth, spec, first, last, color):
    count = min(4096, max(2, int(np.linalg.norm((last-first)[:2])*spec['width']*2)))
    points = np.linspace(first, last, count)
    xy = np.floor(points[:, :2]*[spec['width'], spec['height']]).astype(int)
    valid = np.all(xy >= 0, axis=1) & (xy[:, 0] < spec['width']) & (xy[:, 1] < spec['height'])
    xy, points = xy[valid], points[valid]
    valid = points[:, 2] <= depth[xy[:, 1], xy[:, 0]]+spec['span']*.001
    pixels[xy[valid, 1], xy[valid, 0]] = color


def decorate(pixels, buffer, scene, view):
    display = view.get('display', {})
    if display.get('edges'):
        paths = [np.vstack([t, t[0]]) for i, t in enumerate(buffer['mesh']) if buffer['identities'][i][0] == scene['owner']]
        pixels = lines(pixels, buffer['depth'], view['camera'], paths, [60, 79, 91])
    if display.get('controls'):
        paths = [c['points'] for c in scene.get('controls', []) if len(c['points']) > 1 and c['kind'] in ('guide', 'profile')]
        pixels = lines(pixels, buffer['depth'], view['camera'], paths, [97, 220, 163])
    return pixels
