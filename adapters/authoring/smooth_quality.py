"""Inspect the actual open native assembly and dense spline holdout samples."""
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from ...core.authoring.smooth_native import evaluate, coordinates, faces
from ...core.authoring.surface_checks import crossing
from ...core.authoring.smooth_holdout import expected_mesh
from .smooth_domains import clipped


def tree(vertices, triangles):
    return BVHTree.FromPolygons(np.asarray(vertices).tolist(), np.asarray(triangles).tolist(), all_triangles=True)


def distances(points, vertices, triangles):
    bvh = tree(vertices, triangles)
    return np.asarray([bvh.find_nearest(Vector(p))[3] for p in points])


def inspect(parts, seams, settings):
    checks = [part_check(p, settings) for p in parts]; assembly = combined(parts)
    return dict(parts=checks, assembly=assembly, ready=all(p['ready'] for p in checks) and not assembly['crossing_pairs'],
                anatomical_review='required', bone_clearance='not tested; smoothing can reintroduce bone penetration',
                inflation_fitted=False, solver_calls=0, complete_intersection_certificate=False)


def part_check(part, settings):
    mesh = part.get('retained_native', part['native']); vertices = np.asarray(mesh['vertices']); triangles = np.asarray(mesh['triangles'])
    holdout, target_faces = expected_mesh(part)
    target = clipped(holdout, target_faces, part.get('world_plane')); holdout, target_faces = target['vertices'], target['triangles']
    forward = distances(holdout, vertices, triangles)
    reverse = distances(vertices, holdout, target_faces); quality = overlaps(vertices, triangles)
    maximum = float(max(forward.max(), reverse.max())); fit = part['fit']; reasons = []
    if maximum > settings['max_native_error']: reasons.append('BASE_NATIVE_FIT')
    if fit['maximum']+part.get('partition', {}).get('maximum_displacement', 0) > settings['max_shape_error']: reasons.append('BASE_SHAPE_CHANGE')
    if max(map(abs, fit['width_change'])) > settings.get('max_width_change', .15): reasons.append('BASE_WIDTH_CHANGE')
    if quality['crossing_pairs'] or quality['degenerate_triangles']: reasons.append('BASE_NATIVE_FOLD')
    return dict(id=part['id'], ready=not reasons, reasons=reasons, native_max_distance=maximum,
        native_rms_distance=float(np.sqrt(np.mean(np.r_[forward, reverse]**2))), spatial=quality,
        holdout_grid=[len(part['fibers']), 97], fit=fit)


def overlaps(vertices, triangles):
    bvh = tree(vertices, triangles); scale = max(float(np.linalg.norm(np.ptp(vertices, axis=0))), 1e-10)
    canonical = np.unique(np.rint((vertices-vertices.min(axis=0))/(scale*1e-9)).astype(np.int64), axis=0, return_inverse=True)[1]
    pairs = [(a, b) for a, b in bvh.overlap(bvh) if a < b and not set(canonical[triangles[a]]) & set(canonical[triangles[b]])
             and crossing(vertices[triangles[a]], vertices[triangles[b]])]
    t = vertices[triangles]; areas = np.linalg.norm(np.cross(t[:, 1]-t[:, 0], t[:, 2]-t[:, 0]), axis=1)
    return dict(crossing_pairs=len(pairs), degenerate_triangles=int(sum(areas <= scale*scale*1e-14)),
                method='BVH candidates with triangle crossing; coincident seam vertices welded for adjacency')


def combined(parts):
    vertices, triangles, offset = [], [], 0
    for p in parts:
        mesh = p.get('retained_native', p['native']); v = np.asarray(mesh['vertices']); vertices.append(v)
        triangles.append(np.asarray(mesh['triangles'])+offset); offset += len(v)
    return overlaps(np.concatenate(vertices), np.concatenate(triangles))
