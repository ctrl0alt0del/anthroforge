"""Detached world-space collision queries and reproducible surface sampling."""
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from ...core.authoring.errors import require
from ...core.authoring.base_patch import topology
from ...core.authoring.geometry import contains, ray_hits
from ...core.authoring.surface_checks import crossing
from ...core.authoring.nearest import on_triangles

DIRECTIONS = ((1., .317, .193), (-.219, 1., .431), (.371, -.247, 1.))


def tree(vertices, faces):
    return BVHTree.FromPolygons(vertices.tolist(), faces.tolist(), all_triangles=True, epsilon=0.)


def intersection_extent(first, second):
    points = []
    for source, target in ((first, second), (second, first)):
        for a, b in zip(source, np.roll(source, -1, axis=0)):
            length = np.linalg.norm(b-a)
            if length > 1e-15:
                points.extend(hit[2] for hit in ray_hits(target[None], a, (b-a)/length, length))
    if len(points) >= 2:
        return float(np.linalg.norm(np.asarray(points)[:, None]-points, axis=2).max())
    return float(np.linalg.norm(np.maximum(np.minimum(first.max(axis=0), second.max(axis=0))-np.maximum(first.min(axis=0), second.min(axis=0)), 0)))


def quality(vertices, faces, tolerance=0.):
    bvh = tree(vertices, faces); _points, canonical = np.unique(vertices, axis=0, return_inverse=True)
    epsilon = max(float(np.linalg.norm(np.ptp(vertices, axis=0)))*1e-8, 1e-7)
    pairs = [(a, b) for a, b in bvh.overlap(bvh) if a < b and not set(canonical[faces[a]]) & set(canonical[faces[b]]) and not seam_contact(vertices[faces[a]], vertices[faces[b]], epsilon) and crossing(vertices[faces[a]], vertices[faces[b]])]
    triangles = vertices[faces]; areas = np.linalg.norm(np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]), axis=1)
    small = sum(intersection_extent(vertices[faces[a]], vertices[faces[b]]) <= tolerance for a, b in pairs) if tolerance else 0
    result = topology(faces); result.update(nonadjacent_overlap_pairs=len(pairs)-small, subtolerance_intersection_pairs=small, degenerate_triangles=int(sum(areas <= 1e-16)))
    result['ready'] = not any(result[k] for k in ('boundary_edges', 'nonmanifold_edges', 'nonadjacent_overlap_pairs', 'degenerate_triangles'))
    return result


def seam_contact(first, second, epsilon):
    return bool(np.min(np.linalg.norm(first[:, None]-second, axis=2)) <= epsilon)


def volume(vertices, faces):
    triangles = vertices[faces]-vertices.mean(axis=0)
    return float(np.einsum('ij,ij->i', triangles[:, 0], np.cross(triangles[:, 1], triangles[:, 2])).sum()/6)


def precise_distance(bvh, vertices, faces, point, tolerance):
    hit = bvh.find_nearest(Vector(point)); radius = max(hit[3]+tolerance, tolerance)
    candidates = [h[2] for h in bvh.find_nearest_range(Vector(point), radius)]
    if not candidates:
        candidates = [hit[2]]
    nearest = on_triangles(vertices[faces[candidates]], np.asarray(point))
    distance = float(np.linalg.norm(nearest-point, axis=1).min())
    if distance > tolerance:
        distance = float(np.linalg.norm(on_triangles(vertices[faces], np.asarray(point))-point, axis=1).min())
    return distance


def parity(bvh, point, direction, epsilon):
    origin = Vector(point); direction = Vector(direction).normalized(); count = 0
    for _ in range(256):
        hit = bvh.ray_cast(origin, direction)
        if hit[0] is None:
            return count % 2
        count += 1; origin = hit[0]+direction*epsilon
    return -1


class Obstacle:
    def __init__(self, identity, vertices, faces, tolerance):
        self.identity, self.vertices, self.faces = identity, vertices, faces
        self.tree = tree(vertices, faces); self.tolerance = tolerance
        self.orientation = 1. if volume(vertices, faces) >= 0 else -1.
        self.bounds = (vertices.min(axis=0), vertices.max(axis=0))

    def nearest(self, points):
        hits = [self.tree.find_nearest(Vector(p)) for p in points]
        require(all(h[0] is not None for h in hits), 'COLLISION_QUERY_FAILED')
        return np.array([tuple(h[0]) for h in hits]), np.array([tuple(h[1]) for h in hits])*self.orientation

    def distance(self, points):
        distance, nearest, _ambiguous, _fallback = self.verified(points); delta = points-nearest
        gradient = delta/np.maximum(abs(distance[:, None]), 1e-20)*np.sign(distance[:, None])
        on_surface = abs(distance) < 1e-12
        if on_surface.any():
            gradient[on_surface] = self.nearest(points[on_surface])[1]
        return distance, gradient

    def verified(self, points):
        nearest, _normals = self.nearest(points); distances = np.linalg.norm(points-nearest, axis=1)
        box = np.all((points >= self.bounds[0]) & (points <= self.bounds[1]), axis=1); ambiguous, fallback = 0, 0
        for index in np.flatnonzero(box & (distances > self.tolerance*.1)):
            votes = [parity(self.tree, points[index], d, self.tolerance*.05) for d in DIRECTIONS]
            uncertain = len(set(votes)) != 1 or -1 in votes; fallback += int(uncertain)
            inside = bool(contains(self.vertices[self.faces], [points[index]])[0]) if uncertain else sum(votes) >= 2
            if inside:
                distances[index] *= -1
        return distances, nearest, ambiguous, fallback


def sample(vertices, faces, count):
    tri = vertices[faces]; area = np.linalg.norm(np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0]), axis=1)/2
    require(area.sum() > 0, 'COLLISION_EMPTY_MESH'); rng = np.random.default_rng(2417)
    ids = rng.choice(len(faces), count, p=area/area.sum()); uv = rng.random((count, 2)); uv[uv.sum(axis=1)>1] = 1-uv[uv.sum(axis=1)>1]
    holdout = tri[ids, 0]+uv[:, :1]*(tri[ids, 1]-tri[ids, 0])+uv[:, 1:]*(tri[ids, 2]-tri[ids, 0])
    return np.vstack((vertices, tri.mean(axis=1), holdout)), area


def reverse_containment(vertices, faces, obstacle, tolerance):
    if topology(faces)['boundary_edges']:
        return dict(available=False, contained_samples=0, max_depth=0.)
    muscle = Obstacle('reference', vertices, faces, tolerance)
    points = np.vstack((obstacle.vertices, obstacle.vertices[obstacle.faces].mean(axis=1)))
    distances, _near, _ambiguous, _fallback = muscle.verified(points)
    return dict(available=True, contained_samples=int(sum(distances < -tolerance)), max_depth=float(max(0., -distances.min())))


def report(vertices, faces, obstacle, tolerance, count):
    points, area = sample(vertices, faces, count); distance, near, ambiguous, fallback = obstacle.verified(points); bad = distance < -tolerance
    vertex_bad = bad[:len(vertices)]; face_bad = bad[len(vertices):len(vertices)+len(faces)]
    pairs = tree(vertices, faces).overlap(obstacle.tree)
    return dict(obstacle=obstacle.identity, max_penetration=float(max(0., -distance.min())), inside_vertices=int(sum(vertex_bad)),
                inside_face_centroids=int(sum(face_bad)), inside_holdout=int(sum(bad[len(vertices)+len(faces):])),
                penetrating_vertex_indices=np.flatnonzero(vertex_bad).tolist(), penetrating_triangle_indices=np.flatnonzero(face_bad).tolist(),
                centroid_inside_area=float(area[face_bad].sum()), surface_area=float(area.sum()), triangle_overlap_pairs=len(pairs),
                bounds=[points[bad].min(axis=0).tolist(), points[bad].max(axis=0).tolist()] if bad.any() else [],
                mean_exit_vector=(near[bad]-points[bad]).mean(axis=0).tolist() if bad.any() else [0., 0., 0.],
                ambiguous_samples=ambiguous, winding_fallback_samples=fallback, sample_count=len(points), holdout_count=count, tolerance=tolerance,
                reverse_containment=reverse_containment(vertices, faces, obstacle, tolerance),
                method='vertices, triangle centroids and seeded area samples; three-ray parity with winding fallback; overlaps include contact', clearance_certificate=False)
