"""Indexed, facet-conforming attachment footprints and guarded cut domains."""
import numpy as np
from .errors import require
from .transfer_meshes import world
from .attachment_graft_mesh import boundaries, cut


def patch(geometry, records):
    vertices = world(geometry); valid = {tuple(sorted(t)) for t in geometry['triangles']}; triangles = []; points = []; lookup = {}
    for record in records:
        ids = np.asarray(record['tri_vidx'], int).tolist(); weights = np.asarray(record['polygon'], float)
        require(len(ids) == 3 and tuple(sorted(ids)) in valid, 'ATTACHMENT_PATCH_TRIANGLE')
        require(weights.ndim == 2 and weights.shape[1] == 3 and np.isfinite(weights).all(), 'ATTACHMENT_PATCH_WEIGHTS')
        require((weights >= -1e-9).all() and (weights <= 1+1e-9).all() and np.allclose(weights.sum(1), 1, atol=1e-9), 'ATTACHMENT_PATCH_WEIGHTS')
        polygon = indexed_polygon(ids, weights, vertices, lookup, points)
        triangles.extend([polygon[0], polygon[i], polygon[i+1]] for i in range(1, len(polygon)-1))
    f = np.asarray(triangles, int); _, unique = np.unique(np.sort(f, axis=1), axis=0, return_index=True); f = f[unique]
    return np.asarray(points), f[:, ::-1], one_boundary(f)


def indexed_polygon(ids, weights, vertices, lookup, points):
    polygon = []
    for row in weights:
        key = tuple(sorted((int(i), round(float(w), 9)) for i, w in zip(ids, row) if w > 1e-9))
        if key not in lookup:
            lookup[key] = len(points); points.append(row@vertices[ids])
        polygon.append(lookup[key])
    return polygon


def one_boundary(faces):
    try:
        loops = boundaries(faces)
    except (KeyError, AssertionError):
        require(False, 'ATTACHMENT_NONMANIFOLD_BOUNDARY')
    require(len(loops) == 1, 'ATTACHMENT_SINGLE_BOUNDARY_REQUIRED')
    return loops[0]


def retained(vertices, faces, values, level):
    require(len(values) == len(vertices) and np.isfinite(values).all(), 'ATTACHMENT_CUT_FIELD')
    require(min(values) < level < max(values), 'ATTACHMENT_CUT_EMPTY')
    v, f = cut(vertices, faces, np.asarray(values), level)
    return v, f, one_boundary(f)


def settings_valid(settings):
    require(settings['overlap_cut_value'] < settings['cut_value'], 'ATTACHMENT_CUT_ORDER')
    require(0 < settings['escape_distance'] and 0 < settings['tolerance'], 'ATTACHMENT_SETTINGS')
    axes = np.array([*settings['attachment_axes'], *settings['retained_axes']], float)
    require(axes.shape == (4, 3) and np.isfinite(axes).all(), 'ATTACHMENT_AXES')
    require(np.linalg.norm(np.cross(axes[0], axes[1])) > 1e-10 and np.linalg.norm(np.cross(axes[2], axes[3])) > 1e-10, 'ATTACHMENT_AXES')
    direction = np.array(settings['departure_direction'], float)
    require(direction.shape == (3,) and np.isfinite(direction).all() and np.linalg.norm(direction) > 1e-10, 'ATTACHMENT_DEPARTURE_INVALID')
