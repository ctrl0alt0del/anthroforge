"""Temporary polygon clipping; source vertices and topology remain immutable."""
import numpy as np
from .errors import require


def plane(polygon, normal, distance, epsilon=1e-10):
    result = []
    for first, last in zip(polygon, np.roll(polygon, -1, axis=0)):
        a, b = float(first @ normal-distance), float(last @ normal-distance)
        if a <= epsilon:
            result.append(first)
        if (a < -epsilon and b > epsilon) or (a > epsilon and b < -epsilon):
            result.append(first + (last-first) * a/(a-b))
    return np.asarray(result).reshape((-1, 3))


def partition(polygons, planes, budget):
    inside, outside = list(polygons), []
    for normal, distance in planes:
        remaining = []
        for polygon in inside:
            budget.check()
            a, b = plane(polygon, normal, distance), plane(polygon, -normal, -distance)
            if area(a) > 1e-14:
                remaining.append(a)
            if area(b) > 1e-14:
                outside.append(b)
        inside = remaining
    return inside, outside


def box_planes(low, high):
    low, high = np.asarray(low), np.asarray(high)
    require(np.all(high > low), 'SELECTOR_INVALID_BOUNDS')
    axes = np.eye(3)
    return [(axis, high[i]) for i, axis in enumerate(axes)] + [(-axis, -low[i]) for i, axis in enumerate(axes)]


def area(polygon):
    if len(polygon) < 3:
        return 0.
    return float(np.linalg.norm(np.cross(polygon[1:-1]-polygon[0], polygon[2:]-polygon[0]), axis=1).sum()/2)


def triangulate(polygons):
    return [np.array([p[0], p[i], p[i+1]]) for p in polygons for i in range(1, len(p)-1)]


def subdivide(triangle):
    a, b, c = triangle
    ab, bc, ca = (a+b)/2, (b+c)/2, (c+a)/2
    return [np.array(p) for p in ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca))]


def curved(polygons, signed, depth, budget, lipschitz=None):
    inside, outside = [], []
    for triangle in triangulate(polygons):
        budget.check()
        a, b = curved_triangle(triangle, signed, depth, budget, lipschitz)
        inside.extend(a)
        outside.extend(b)
    return inside, outside


def curved_triangle(triangle, signed, depth, budget, lipschitz):
    values = np.array([signed(p) for p in triangle])
    if lipschitz is not None:
        bound = lipschitz*max(np.linalg.norm(a-b) for a in triangle for b in triangle)
        if max(values) < -bound:
            return [triangle], []
        if min(values) > bound:
            return [], [triangle]
    if depth:
        return curved(subdivide(triangle), signed, depth-1, budget, lipschitz)
    return linear_cut(triangle, values)


def linear_cut(triangle, values):
    if np.all(values <= 0):
        return [triangle], []
    if np.all(values > 0):
        return [], [triangle]
    gradient = np.linalg.lstsq(np.c_[triangle, np.ones(3)], values, rcond=None)[0]
    a = plane(triangle, gradient[:3], -gradient[3])
    b = plane(triangle, -gradient[:3], gradient[3])
    return ([a] if area(a) > 1e-14 else []), ([b] if area(b) > 1e-14 else [])


def connected(polygons, seed, tolerance):
    require(tolerance > 0, 'INVALID_TOLERANCE')
    keys = [{tuple(np.round(p/tolerance).astype(int)) for p in poly} for poly in polygons]
    seeds = [i for i, p in enumerate(polygons) if point_in_polygon(seed, p, tolerance)]
    require(len(seeds) > 0, 'SEED_OUTSIDE_REGION')
    require(sum(interior(seed, polygons[i], tolerance) for i in seeds) <= 1, 'AMBIGUOUS_SURFACE_SHEET')
    seen, pending = set(), list(seeds)
    while pending:
        current = pending.pop()
        if current not in seen:
            seen.add(current)
            pending.extend(i for i, k in enumerate(keys) if i not in seen and keys[current] & k)
    return [p for i, p in enumerate(polygons) if i in seen]


def interior(point, polygon, tolerance):
    normal = np.cross(polygon[1]-polygon[0], polygon[2]-polygon[0])
    for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
        if np.cross(b-a, np.asarray(point)-a) @ normal <= tolerance*np.linalg.norm(normal)*np.linalg.norm(b-a):
            return False
    return True


def point_in_polygon(point, polygon, tolerance=1e-7):
    point = np.asarray(point)
    for tri in triangulate([polygon]):
        a, b, c = tri
        uv = np.linalg.lstsq(np.array([b-a, c-a]).T, point-a, rcond=None)[0]
        if min(uv) >= -tolerance and sum(uv) <= 1+tolerance and np.linalg.norm(a+uv[0]*(b-a)+uv[1]*(c-a)-point) <= tolerance:
            return True
    return False
