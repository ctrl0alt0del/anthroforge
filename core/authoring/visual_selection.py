"""Polygon selection clips actual visible surface fragments, including occlusion."""
import numpy as np
from .errors import require
from .trims import triangulate as triangulate_mask
from . import clipping, visual_camera as camera, visual_mesh as mesh
from .model import Budget


def planes(polygon):
    points = np.asarray(polygon)
    area = sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(points, np.roll(points, -1, axis=0)))
    points = points if area > 0 else points[::-1]
    return [edge_plane(a, b) for a, b in zip(points, np.roll(points, -1, axis=0)) if np.linalg.norm((b-a)[:2]) > 1e-12]


def edge_plane(a, b):
    normal = np.array([b[1]-a[1], a[0]-b[0], 0], dtype=float)
    normal /= np.linalg.norm(normal)
    return normal, float(normal[:2] @ a[:2])


def projected_mesh(scene, view):
    triangles, identities = mesh.triangles(scene)
    screen, indices = [], []
    for index, triangle in enumerate(triangles):
        for fragment in mesh.clipped(triangle, view.get('section')):
            projected = camera.project(view['camera'], fragment)
            if abs(np.linalg.det(np.c_[projected[:, :2], np.ones(3)])) > 1e-12:
                screen.append(projected)
                indices.append(index)
    return triangles, identities, np.asarray(screen).reshape((-1, 3, 3)), indices


def select(scene, view, polygon, budget=None):
    budget = budget or Budget(milliseconds=30000, maximum=300000)
    require(np.all(np.isfinite(polygon)) and np.min(polygon) >= 0 and np.max(polygon) <= 1, 'VIEW_COORDINATE_INVALID')
    masks = triangulate_mask(polygon)
    triangles, identities, screen, indices = projected_mesh(scene, view)
    result = []
    for index, triangle in enumerate(screen):
        budget.check()
        if identities[indices[index]][0] != scene['owner']:
            continue
        pieces = masked(triangle, masks, budget)
        pieces = visible(pieces, index, screen, indices, view['camera']['span'], budget)
        result.extend(dict(triangle=identities[indices[index]][1], polygon=mesh.barycentric(triangles[indices[index]], camera.unproject(view['camera'], p)).tolist()) for p in pieces)
    return result


def masked(triangle, masks, budget):
    return [p for mask in masks for p in clipping.partition([triangle], planes(mask), budget)[0] if clipping.area(p) > 1e-12]


def visible(pieces, index, screen, indices, span, budget):
    if not pieces:
        return []
    bounds = np.concatenate(pieces)
    candidates = occluders(screen, bounds.min(0), bounds.max(0), span)
    for other in candidates:
        if indices[other] == indices[index]:
            continue
        budget.check()
        a, b, c = np.linalg.solve(np.c_[screen[other, :, :2], np.ones(3)], screen[other, :, 2])
        tolerance = span*1e-9*(-1 if indices[other] < indices[index] else 1)
        _, pieces = clipping.partition(pieces, planes(screen[other])+[(np.array([a, b, -1]), -c-tolerance)], budget)
        if not pieces:
            break
    return pieces


def occluders(screen, low, high, span):
    return np.flatnonzero(np.all(screen.max(1)[:, :2] >= low[:2], axis=1) & np.all(screen.min(1)[:, :2] <= high[:2], axis=1) & (screen.min(1)[:, 2] <= high[2]+span*1e-9))


def combine(previous, additional, mode, budget=None):
    budget = budget or Budget(maximum=300000)
    result = list(previous)
    for row in additional:
        polygon = np.asarray(row['polygon'])[:, [1, 2, 0]]
        matching = [r for r in result if r['triangle'] == row['triangle']]
        if mode == 'add':
            pieces = [polygon]
            for old in matching:
                _, pieces = clipping.partition(pieces, planes(np.asarray(old['polygon'])[:, [1, 2, 0]]), budget)
            result.extend(dict(triangle=row['triangle'], polygon=p[:, [2, 0, 1]].tolist()) for p in pieces)
        else:
            result = subtract(result, row, polygon, budget)
    return result


def subtract(rows, row, polygon, budget):
    result = [r for r in rows if r['triangle'] != row['triangle']]
    for old in rows:
        if old['triangle'] == row['triangle']:
            _, pieces = clipping.partition([np.asarray(old['polygon'])[:, [1, 2, 0]]], planes(polygon), budget)
            result.extend(dict(triangle=row['triangle'], polygon=p[:, [2, 0, 1]].tolist()) for p in pieces)
    return result


def world_polygons(geometry, patches):
    triangles = mesh.vertices(geometry)[np.asarray(geometry['triangles'], dtype=int)]
    result = []
    for row in patches:
        require(0 <= row['triangle'] < len(triangles), 'SURFACE_PATCH_INVALID')
        weights = np.asarray(row['polygon'])
        require(weights.shape[1] == 3 and np.all(np.isfinite(weights)) and weights.min() >= -1e-7 and weights.max() <= 1+1e-7 and np.allclose(weights.sum(1), 1), 'SURFACE_PATCH_INVALID')
        result.append(weights @ triangles[row['triangle']])
    return result


def area(geometry, patches):
    return sum(clipping.area(p) for p in world_polygons(geometry, patches))
