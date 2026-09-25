"""Area coverage of complete coplanar footprint triangles, not contact vertices only."""
import numpy as np


def area(poly):
    if len(poly) < 3:
        return 0.
    p = np.asarray(poly); q = np.roll(p, -1, axis=0)
    return abs(float((p[:, 0]*q[:, 1]-p[:, 1]*q[:, 0]).sum()))*.5


def halfplane(poly, a, b, sign):
    result = []; edge = b-a
    for p, q in zip(poly, np.roll(poly, -1, axis=0)):
        dp = sign*(edge[0]*(p[1]-a[1])-edge[1]*(p[0]-a[0])); dq = sign*(edge[0]*(q[1]-a[1])-edge[1]*(q[0]-a[0]))
        if dp >= 0:
            result.append(p)
        if dp*dq < 0:
            result.append(p+(q-p)*dp/(dp-dq))
    return result


def intersection(poly, triangle):
    a, b, c = triangle; sign = np.sign((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))
    for a, b in zip(triangle, np.roll(triangle, -1, axis=0)):
        poly = halfplane(poly, a, b, sign)
        if len(poly) < 3:
            return 0.
    return area(poly)


def coverage(vertices, faces, patch_vertices, patch_faces, tolerance):
    triangles = vertices[faces]; totals = []; missing = []
    for triangle in patch_vertices[patch_faces]:
        normal = np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0]); length = np.linalg.norm(normal)
        if length <= 1e-15:
            continue
        normal /= length; axes = [i for i in range(3) if i != np.argmax(abs(normal))]; projected = triangle[:, axes]
        coplanar = abs(np.einsum('ijk,k->ij', triangles-triangle[0], normal)).max(1) <= tolerance
        bounds = (triangles.min(1) <= triangle.max(0)+tolerance).all(1)&(triangles.max(1) >= triangle.min(0)-tolerance).all(1)
        covered = sum(intersection(t[:, axes], projected) for t in triangles[coplanar&bounds]); target = area(projected)
        totals.append(length*.5); missing.append(max(0., 1-covered/max(target, 1e-30))*length*.5)
    ratio = sum(missing)/max(sum(totals), 1e-30)
    return dict(footprint_area=sum(totals), uncovered_area=sum(missing), covered_fraction=1-ratio, triangle_count=len(totals), plane_tolerance=tolerance)
