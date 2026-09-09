"""Simple polygon trims and bounded sampling without probing outside the region."""
import numpy as np
from .errors import require


def cross(a, b, c):
    x, y = np.asarray(b)-a, np.asarray(c)-a
    return float(x[0]*y[1]-x[1]*y[0])


def triangulate(polygon):
    require(len(set(map(tuple,polygon))) == len(polygon), "DUPLICATE_TRIM_VERTEX")
    simple(polygon)
    area = sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(polygon,polygon[1:]+polygon[:1]))
    require(abs(area) > 1e-12, "DEGENERATE_TRIM")
    points = list(polygon if area > 0 else polygon[::-1])
    result = []
    while len(points) > 3:
        index = next((i for i in range(len(points)) if ear(points,i)),None)
        require(index is not None, "INVALID_TRIM")
        result.append((points[index-1],points[index],points[(index+1)%len(points)]))
        points.pop(index)
    return result+[tuple(points)]


def simple(points):
    n = len(points)
    for i in range(n):
        for j in range(i+1,n):
            if (j-i)%n not in (1,n-1):
                require(not segments_cross(points[i],points[(i+1)%n],points[j],points[(j+1)%n]), "SELF_INTERSECTING_TRIM")


def segments_cross(a,b,c,d):
    overlap = np.all(np.maximum(np.minimum(a,b),np.minimum(c,d)) <= np.minimum(np.maximum(a,b),np.maximum(c,d))+1e-12)
    return overlap and cross(a,b,c)*cross(a,b,d) <= 0 and cross(c,d,a)*cross(c,d,b) <= 0


def ear(points, index):
    n = len(points)
    a,b,c = points[index-1],points[index],points[(index+1)%n]
    if cross(a,b,c) <= 1e-12:
        return False
    return not any(in_triangle(p,a,b,c) for i,p in enumerate(points) if i not in ((index-1)%n,index,(index+1)%n))


def in_triangle(point, a, b, c):
    return min(cross(a,b,point),cross(b,c,point),cross(c,a,point)) >= -1e-12


def resolve(resolver, name, polygon):
    for triangle in triangulate(polygon):
        refine(resolver,name,triangle)


def refine(resolver, name, triangle, depth=0):
    from .regions import refine_edge
    points = [np.asarray(p) for p in triangle]
    anchors = [resolver.point(name, tuple(p)) for p in points]
    middle = np.mean(points,axis=0)
    actual = resolver.point(name,tuple(middle))
    error = np.linalg.norm(np.asarray(actual.point)-np.mean([a.point for a in anchors],axis=0))
    limit = resolver.measure(resolver.document["regions"][name]["projection"]["max_surface_error"])
    for a,b in zip(points,points[1:]+points[:1]):
        refine_edge(resolver,name,tuple(a),tuple(b))
        if error > limit:
            require(depth < 12, "REGION_DISCONTINUOUS")
            refine(resolver,name,(a,b,middle),depth+1)
