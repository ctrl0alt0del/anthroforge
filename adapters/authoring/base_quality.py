"""Detached spatial checks for experimental reconstructed base geometry."""
from mathutils.bvhtree import BVHTree
import numpy as np


def inspect(vertices, triangles):
    vertices, triangles = np.asarray(vertices), np.asarray(triangles)
    tree = BVHTree.FromPolygons(vertices.tolist(), triangles.tolist(), all_triangles=True, epsilon=0.)
    pairs = {(min(a, b), max(a, b)) for a, b in tree.overlap(tree)
             if a != b and not set(triangles[a]).intersection(triangles[b])}
    corners = vertices[triangles]; areas = np.linalg.norm(np.cross(corners[:, 1]-corners[:, 0], corners[:, 2]-corners[:, 0]), axis=1)
    degenerate = int(np.count_nonzero(areas <= max(areas.max()*1e-12, 1e-24)))
    return dict(nonadjacent_bvh_overlap_pairs=len(pairs), degenerate_triangles=degenerate, method='Blender BVH triangle overlap; shared-vertex pairs excluded',
                complete_intersection_certificate=False)
