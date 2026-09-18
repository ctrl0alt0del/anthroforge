"""Experimental disk reconstruction from a supplied underside and outer perimeter."""
import numpy as np
from .errors import require


def perimeter(vertices, loop, count):
    points = vertices[np.asarray(loop, dtype=int)]; closed = np.vstack((points, points[:1]))
    distances = np.linalg.norm(np.diff(closed, axis=0), axis=1); cumulative = np.r_[0., np.cumsum(distances)]
    require(np.all(distances > 1e-12), 'BASE_DEGENERATE_PERIMETER')
    t = np.arange(count)*cumulative[-1]/count; ids = np.minimum(np.searchsorted(cumulative, t, side='right')-1, len(points)-1)
    weights = (t-cumulative[ids])/distances[ids]
    return closed[ids]*(1-weights[:, None])+closed[ids+1]*weights[:, None]


def disk(count, rings):
    angles = np.arange(count)*2*np.pi/count; circle = np.c_[np.cos(angles), np.sin(angles)]
    uv = np.vstack(([[0., 0.]], *[circle*(r/rings) for r in range(1, rings+1)]))
    faces = [[0, 1+i, 1+(i+1) % count] for i in range(count)]
    for ring in range(1, rings):
        for i in range(count):
            a, b = 1+(ring-1)*count+i, 1+(ring-1)*count+(i+1) % count; c, d = a+count, b+count
            faces.extend(((a, c, d), (a, d, b)))
    return uv, np.asarray(faces, dtype=int), np.arange(1+(rings-1)*count, 1+rings*count)


def laplacian(uv, faces):
    edges = np.unique(np.sort(faces[:, [[0, 1], [1, 2], [2, 0]]].reshape(-1, 2), axis=1), axis=0)
    a, b = edges.T; matrix = np.zeros((len(uv), len(uv))); weights = 1/np.maximum(np.linalg.norm(uv[a]-uv[b], axis=1), 1e-12)
    matrix[a, b] = matrix[b, a] = weights; sums = matrix.sum(1)
    return np.eye(len(uv))-matrix/sums[:, None]


def samples(vertices, faces):
    triangles = vertices[faces]; area = np.linalg.norm(np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]), axis=1)/2
    require(area.sum() > 1e-14, 'BASE_EMPTY_AREA')
    points = np.concatenate((triangles.mean(1), triangles[:, 0]*.6+triangles[:, 1]*.2+triangles[:, 2]*.2,
                             triangles[:, 1]*.6+triangles[:, 0]*.2+triangles[:, 2]*.2))
    return points, np.tile(area/area.sum()/3, 3)


def correspondence(points, vertices):
    ids, distances = [], []
    for start in range(0, len(points), 128):
        delta = points[start:start+128, None]-vertices; square = np.einsum('nkd,nkd->nk', delta, delta)
        nearest = np.argmin(square, axis=1); ids.extend(nearest); distances.extend(square[np.arange(len(nearest)), nearest])
    return np.asarray(ids), np.sqrt(distances)


def targets(points, weights, current):
    ids, _distances = correspondence(points, current); count = len(current)
    mass = np.bincount(ids, weights=weights, minlength=count)*count
    value = np.column_stack([np.bincount(ids, weights=weights*points[:, axis], minlength=count) for axis in range(3)])*count
    return mass, value


def iterate(current, boundary, fair, source, weights, regularization):
    inside = np.setdiff1d(np.arange(len(current)), boundary); mass, value = targets(source, weights, current)
    system = fair*regularization+np.diag(mass+1e-9)
    rhs = value[inside]-system[np.ix_(inside, boundary)] @ current[boundary]
    result = current.copy(); result[inside] = np.linalg.solve(system[np.ix_(inside, inside)], rhs)
    return result


def fit(vertices, triangles, loop, settings):
    boundary = perimeter(vertices, loop, settings.get('boundary_samples', 96))
    return fit_boundary(vertices, triangles, boundary, settings)


def fit_boundary(vertices, triangles, boundary_points, settings):
    count, rings = len(boundary_points), settings.get('rings', 5)
    uv, faces, boundary = disk(count, rings); L = laplacian(uv, faces); inside = np.setdiff1d(np.arange(len(uv)), boundary)
    current = np.zeros((len(uv), 3)); current[boundary] = boundary_points
    current[inside] = np.linalg.solve(L[np.ix_(inside, inside)], -L[np.ix_(inside, boundary)] @ current[boundary])
    points, weights = samples(vertices, triangles); fair = L.T @ L
    for _step in range(settings.get('iterations', 8)):
        current = iterate(current, boundary, fair, points, weights, settings.get('regularization', .4))
    return dict(vertices=current, triangles=faces, uv=uv, boundary=boundary, source_points=points, source_weights=weights)


def topology(faces):
    edges, counts = np.unique(np.sort(faces[:, [[0, 1], [1, 2], [2, 0]]].reshape(-1, 2), axis=1), axis=0, return_counts=True)
    boundary = edges[counts == 1]; _ids, degrees = np.unique(boundary, return_counts=True)
    return dict(euler=int(len(np.unique(faces))-len(edges)+len(faces)), boundary_edges=int(len(boundary)),
                nonmanifold_edges=int((counts > 2).sum()), pinched_boundary_vertices=int((degrees != 2).sum()),
                connected_components=component_count(edges), boundary_components=component_count(boundary))


def leader(parents, index):
    while parents[index] != index:
        parents[index] = parents[parents[index]]; index = parents[index]
    return index


def component_count(edges):
    parents = {int(i): int(i) for i in np.unique(edges)}
    for a, b in edges:
        parents[leader(parents, a)] = leader(parents, b)
    return len({leader(parents, i) for i in parents})
