"""Inflated-surface intersection evidence and bounded acceptance."""
import numpy as np
from .geometry import triangles, contains, closed_mesh, surface_distance, ray_hits
from .errors import require
from .contact_components import components, retained


def evaluate(vertices, quads, snapshot, tolerance):
    return evaluate_bounded(vertices,quads,snapshot,tolerance,lambda:None)


def evaluate_bounded(vertices, quads, snapshot, tolerance, check):
    indices = np.vstack((quads[:, :3], quads[:, [0, 2, 3]]))
    surface = np.asarray(vertices)[indices]
    affected, depths, blockers = set(), [], set()
    for mesh in snapshot.meshes:
        require(closed_mesh(mesh), "COLLIDER_AMBIGUOUS", mesh.id)
        collider = triangles(mesh)
        for index in collider_candidates(surface, collider):
            check()
            tri = surface[index]
            depth = triangle_depth(tri, collider, tolerance)
            if depth > tolerance:
                affected.add(int(index)); depths.append(depth); blockers.add(mesh.id)
    return contact_report(indices,surface,affected,depths,blockers)


def contact_report(indices,surface,affected,depths,blockers):
    areas = np.linalg.norm(np.cross(surface[:,1]-surface[:,0], surface[:,2]-surface[:,0]), axis=1)/2
    return dict(area=float(sum(areas[i] for i in affected)), depth=max(depths, default=0.), triangles=sorted(affected),
                blockers=sorted(blockers), components=components(indices,surface,affected))


def collider_candidates(surface, collider):
    return np.flatnonzero(np.all(surface.max(1) >= collider.min((0,1)),axis=1)
                         & np.all(surface.min(1) <= collider.max((0,1)),axis=1))


def overlapping(tri, collider):
    return bool(np.all(tri.max(axis=0) >= collider.min(axis=(0,1))) and np.all(tri.min(axis=0) <= collider.max(axis=(0,1))))


def triangle_depth(tri, collider, tolerance):
    points = list(tri) + [tri.mean(axis=0)] + interior_slice(tri, collider)
    for a,b in ((0,1),(1,2),(2,0)):
        delta = tri[b]-tri[a]
        size = np.linalg.norm(delta)
        if size < 1e-12:
            continue
        cuts = sorted(set([0., float(size)] + [h[0] for h in ray_hits(collider,tri[a],delta/size,size)]))
        points.extend(tri[a] + delta * ((x+y)/(2*size)) for x,y in zip(cuts,cuts[1:]))
    inside = contains(collider, points)
    return max((surface_distance(collider, p) for p,valid in zip(points,inside) if valid), default=0.)


def interior_slice(tri, collider):
    near = collider[np.all(collider.max(axis=1) >= tri.min(axis=0), axis=1)
                    & np.all(collider.min(axis=1) <= tri.max(axis=0), axis=1)]
    points = []
    for face in near:
        for a, b in ((0,1),(1,2),(2,0)):
            delta = face[b]-face[a]
            length = np.linalg.norm(delta)
            if length > 1e-12:
                points.extend(h[2] for h in ray_hits(tri[None], face[a], delta/length, length))
    if len(points) < 2:
        return []
    center = np.mean(points, axis=0)
    return [center] + [(point+center)/2 for point in points]


def acceptable(before, after, ratio, tolerance):
    return (after["area"] <= before["area"] * (1-ratio)
            and after["depth"] <= before["depth"] + tolerance
            and set(after["blockers"]) <= set(before["blockers"])
            and retained(before, after, tolerance))
