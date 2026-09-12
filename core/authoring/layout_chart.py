"""Positive mean-value harmonic rectangle, using numpy only; reject invalid charts.

Boundary order is start-left, start-right, end-right, end-left. Interior edge
midpoints in layout_patch prevent collinear boundary ears from collapsing.
"""
import numpy as np
from .errors import require
from .layout_linear import solve


def parameterize(patch, corners):
    boundary = orient_boundary(patch, corners)
    uv = np.zeros((len(patch['vertices']), 2))
    positions = [int(np.flatnonzero(boundary == index)[0]) for index in corners]+[len(boundary)]
    rectangle = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]])
    for i in range(4):
        indices = np.append(boundary, boundary[0])[positions[i]:positions[i+1]+1]
        lengths = np.r_[0., np.cumsum(np.linalg.norm(np.diff(patch['vertices'][indices], axis=0), axis=1))]
        require(lengths[-1] > patch['scale']*1e-10, 'LAYOUT_LANDMARK_ORDER')
        uv[indices] = rectangle[i]+(lengths/lengths[-1])[:, None]*(rectangle[i+1]-rectangle[i])
    uv = harmonic(patch, uv, boundary)
    signed = determinants(uv[patch['faces']])
    require(np.all(signed > 1e-12) or np.all(signed < -1e-12), 'LAYOUT_CHART_FOLDED')
    patch['uv'] = uv
    return patch


def landmark_vertices(patch, points):
    boundary = patch['boundary']
    distances = np.linalg.norm(patch['vertices'][boundary, None]-np.asarray(points)[None], axis=2)
    nearest = np.argmin(distances, axis=0)
    require(np.all(distances[nearest, np.arange(4)] <= patch['scale']*1e-6), 'LAYOUT_LANDMARK_NOT_BOUNDARY_VERTEX', 'Choose four distinct vertices on the selected area boundary.')
    corners = boundary[nearest].tolist()
    require(len(set(corners)) == 4, 'LAYOUT_LANDMARK_ORDER', 'The four landmarks must be distinct.')
    return corners


def orient_boundary(patch, corners):
    boundary = patch['boundary'].tolist()
    for trial in (boundary, list(reversed(boundary))):
        start = trial.index(corners[0])
        trial = trial[start:]+trial[:start]
        positions = [trial.index(index) for index in corners]
        if positions == sorted(positions):
            return np.asarray(trial, dtype=int)
    require(False, 'LAYOUT_LANDMARK_ORDER', 'Expected start-left, start-right, end-right, end-left around the boundary.')


def harmonic(patch, uv, boundary):
    a, b, weights = mean_value_weights(patch)
    degree = np.bincount(a, weights=weights, minlength=len(uv))
    weights /= degree[a]
    interior = np.setdiff1d(np.arange(len(uv)), boundary)
    apply = lambda values: multiply(a, b, weights, interior, values, len(uv))
    for axis in range(2):
        rhs = np.bincount(a, weights=weights*uv[b, axis], minlength=len(uv))[interior]
        uv[interior, axis] = solve(apply, rhs)
    return uv


def multiply(a, b, weights, interior, values, count):
    full = np.zeros(count)
    full[interior] = values
    return (full-np.bincount(a, weights=weights*full[b], minlength=count))[interior]


def mean_value_weights(patch):
    faces, vertices = patch['faces'], patch['vertices']/patch['scale']
    rows = []
    for corner in range(3):
        i, j, k = faces[:, corner], faces[:, (corner+1)%3], faces[:, (corner+2)%3]
        a, b = vertices[j]-vertices[i], vertices[k]-vertices[i]
        da, db = np.linalg.norm(a, axis=1), np.linalg.norm(b, axis=1)
        cross = np.linalg.norm(np.cross(a, b), axis=1)
        require(np.all(cross > 1e-16), 'LAYOUT_DEGENERATE_PATCH')
        half = cross/np.maximum(da*db+np.einsum('ij,ij->i', a, b), 1e-30)
        rows.extend((np.column_stack((i, j, half/da)), np.column_stack((i, k, half/db))))
    packed = np.concatenate(rows)
    return packed[:, 0].astype(int), packed[:, 1].astype(int), packed[:, 2]


def determinants(triangles):
    a, b = triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]
    return a[:, 0]*b[:, 1]-a[:, 1]*b[:, 0]


def sample(patch, coordinates, budget):
    uv = patch['uv'][patch['faces']]
    inverse = np.linalg.inv(np.stack((uv[:, 1]-uv[:, 0], uv[:, 2]-uv[:, 0]), axis=2))
    output = []
    for point in coordinates:
        budget.check()
        weights = np.einsum('nij,nj->ni', inverse, point-uv[:, 0])
        bary = np.column_stack((1-weights.sum(axis=1), weights))
        hits = np.flatnonzero(np.min(bary, axis=1) >= -1e-8)
        require(len(hits) > 0, 'LAYOUT_CHART_UNCOVERED')
        index = int(hits[0])
        output.append(bary[index] @ patch['vertices'][patch['faces'][index]])
    return np.asarray(output)
