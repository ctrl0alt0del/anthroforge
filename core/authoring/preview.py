"""Consistent owner-local orthographic region/candidate assets."""
from html import escape
import numpy as np


def svg(polygons, title, bounds=None):
    points = np.array([p for poly in polygons for p in poly]).reshape((-1, 3))
    if not len(points):
        return '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="80"><text x="15" y="35">'+escape(title)+': geometry unavailable</text></svg>'
    low, high = bounds or (points.min(axis=0), points.max(axis=0))
    scale = 250/max(float(max(high-low)), 1e-9)
    panels = [panel(polygons, axes, low, scale, i) for i, axes in enumerate(((0, 1), (0, 2), (1, 2)))]
    return '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="350" viewBox="0 0 960 350"><rect width="960" height="350" fill="#182128"/><text x="15" y="24" fill="white">'+escape(title)+' — coordinate views; anatomical orientation requires a profile</text>'+''.join(panels)+'</svg>'


def panel(polygons, axes, low, scale, index):
    paths = []
    for polygon in polygons:
        points = [(np.asarray(p)-low)*scale for p in polygon]
        coords = ' '.join(f'{index*320+25+p[axes[0]]:.3f},{315-p[axes[1]]:.3f}' for p in points)
        if len(points) == 1:
            paths.append(f'<circle cx="{index*320+25+points[0][axes[0]]}" cy="{315-points[0][axes[1]]}" r="3" fill="#ffba62"/>')
        paths.append(f'<polygon points="{coords}" fill="#72bda5" fill-opacity=".65" stroke="#d0eadf" stroke-width=".35"/>')
    return ''.join(paths)


def scene_bounds(inventory):
    chunks = []
    for geometry in inventory['geometry'].values():
        matrix = np.asarray(geometry['matrix'])
        points = np.asarray(geometry['vertices']) @ matrix[:3, :3].T+matrix[:3, 3]
        chunks.extend([points.min(axis=0), points.max(axis=0)])
    return (np.min(chunks, axis=0), np.max(chunks, axis=0)) if chunks else None
