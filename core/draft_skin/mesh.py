import numpy as np
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from skimage import measure

from .constants import TAUBIN_ITERATIONS, TAUBIN_LAMBDA, TAUBIN_MU
from .status import check_cancelled


def extract_mesh(field, origin, voxel):
    values = np.asarray(field, dtype=np.float32)
    vertices, faces, _normals, _values = measure.marching_cubes(values, 0.0, spacing=(voxel,) * 3, allow_degenerate=False)
    return (vertices + origin).astype(np.float32), faces.astype(np.int32)


def face_edges(faces):
    return np.sort(np.vstack((faces[:, :2], faces[:, 1:], faces[:, ::2])), axis=1)


def adjacency_matrix(vertex_count, faces):
    edges = face_edges(faces)
    directed = np.vstack((edges, edges[:, ::-1]))
    values = np.ones(len(directed), dtype=np.float32)
    return coo_matrix((values, (directed[:, 0], directed[:, 1])), shape=(vertex_count,) * 2).tocsr()


def largest_component(vertices, faces):
    graph = adjacency_matrix(len(vertices), faces)
    _count, labels = connected_components(graph, directed=False)
    face_labels = labels[faces[:, 0]]
    winner = np.bincount(face_labels).argmax()
    selected = faces[face_labels == winner]
    used = np.unique(selected)
    remap = np.full(len(vertices), -1, dtype=np.int32)
    remap[used] = np.arange(len(used), dtype=np.int32)
    return vertices[used], remap[selected]


def smooth_mesh(vertices, faces, progress=None, cancelled=None):
    adjacency = adjacency_matrix(len(vertices), faces)
    result = vertices.astype(np.float64)
    for index in range(TAUBIN_ITERATIONS):
        check_cancelled(cancelled)
        result = _smooth_pass(result, adjacency, TAUBIN_LAMBDA)
        result = _smooth_pass(result, adjacency, TAUBIN_MU)
        _notify(progress, index + 1, TAUBIN_ITERATIONS)
    return result.astype(np.float32)


def _smooth_pass(vertices, adjacency, factor):
    degree = np.asarray(adjacency.sum(axis=1)).ravel()
    neighbor_mean = adjacency @ vertices / degree[:, None]
    return vertices + (float(factor) * (neighbor_mean - vertices))


def orient_outward(vertices, faces):
    return faces[:, ::-1].copy() if signed_volume(vertices, faces) < 0.0 else faces


def signed_volume(vertices, faces):
    triangles = vertices[faces].astype(np.float64)
    crosses = np.cross(triangles[:, 1], triangles[:, 2])
    return float(np.einsum("ij,ij->i", triangles[:, 0], crosses).sum() / 6.0)


def sample_grid(grid, vertices, origin, voxel):
    coordinates = ((np.asarray(vertices) - origin) / voxel).T
    return ndimage.map_coordinates(grid, coordinates, order=1, mode="nearest").astype(np.float32)


def _notify(progress, current, total):
    if progress:
        progress(float(current) / max(1, int(total)))
