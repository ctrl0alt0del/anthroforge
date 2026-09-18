"""Indexed, explicit whole-underside patches; heads are anatomical inputs."""
import numpy as np
from .errors import require
from .base_patch import topology
from .layout_patch import mesh
from .layout_chart import landmark_vertices, parameterize


def define(vertices, triangles, heads, patches):
    vertices, triangles = np.asarray(vertices, float), np.asarray(triangles, int)
    names = [head['id'] for head in heads]
    require(names and len(set(names)) == len(names), 'BASE_INVALID_HEADS')
    require(len({p['id'] for p in patches}) == len(patches), 'BASE_INVALID_PATCHES')
    results = [define_patch(vertices, triangles, p, names) for p in patches]
    require(set(names) == {h for p in results for h in p['head_ids']}, 'BASE_UNUSED_HEAD')
    selections = [i for p in patches for i in p['source_triangles']]
    require(len(selections) == len(set(selections)), 'BASE_OVERLAPPING_PATCH_SELECTIONS')
    return dict(version='muscle_base.v1', heads=heads, patches=results,
                limitations=['Heads and whole-underside completeness require anatomical review.',
                             'Each patch is a disk; separate patches become coordinated native lofts.'])


def define_patch(vertices, triangles, patch, heads):
    ids = patch['source_triangles']; corners = patch['boundary_vertex_ids']
    require(ids and min(ids) >= 0 and max(ids) < len(triangles), 'BASE_INVALID_SOURCE_SELECTION')
    require(len(set(ids)) == len(ids), 'BASE_DUPLICATE_TRIANGLE')
    require(set(patch['head_ids']) <= set(heads) and patch['head_ids'], 'BASE_UNKNOWN_HEAD')
    require(len(corners) == 4 and min(corners) >= 0 and max(corners) < len(vertices), 'BASE_INVALID_CORNERS')
    faces = triangles[ids]; report = topology(faces)
    require(report['euler'] == report['connected_components'] == report['boundary_components'] == 1, 'BASE_REQUIRES_DISK')
    require(not report['nonmanifold_edges'] and not report['pinched_boundary_vertices'], 'BASE_NONMANIFOLD')
    chart = mesh(list(vertices[faces])); corner_points = vertices[corners]
    parameterize(chart, landmark_vertices(chart, corner_points))
    used, mapped = np.unique(faces, return_inverse=True)
    return dict(patch, topology=report, corners=corner_points.tolist(),
                vertices=vertices[used].tolist(), triangles=mapped.reshape(-1, 3).tolist())
