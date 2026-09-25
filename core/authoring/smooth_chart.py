"""Indexed charts with native harmonic solve, then read-only grid sampling."""
from ctypes import POINTER, c_int, c_int64, c_double
import numpy as np
from . import layout_chart as chart
from .layout_patch import mesh
from .model import Budget
from .smooth_native import library, coordinates
from .errors import require


def harmonic(patch, uv, boundary):
    a, b, weights = chart.mean_value_weights(patch); edges = np.ascontiguousarray(np.c_[a, b], dtype=np.int64)
    weights = np.ascontiguousarray(weights, dtype=float)
    fixed = np.zeros(len(uv), np.int64); fixed[boundary] = 1; uv = np.ascontiguousarray(uv)
    lib = library(); i, d = POINTER(c_int64), POINTER(c_double)
    lib.af_base_harmonic.argtypes = [i, d, c_int, i, c_int, d]; lib.af_base_harmonic.restype = c_int
    code = lib.af_base_harmonic(edges.ctypes.data_as(i), weights.ctypes.data_as(d), len(edges),
                                fixed.ctypes.data_as(i), len(uv), uv.ctypes.data_as(d))
    require(code == 0, 'BASE_CHART_UNRESOLVED', str(code)); return uv


def parameterize(patch, corners):
    boundary = chart.orient_boundary(patch, corners); uv = np.zeros((len(patch['vertices']), 2))
    positions = [int(np.flatnonzero(boundary == i)[0]) for i in corners]+[len(boundary)]
    rectangle = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]])
    for i in range(4):
        ids = np.append(boundary, boundary[0])[positions[i]:positions[i+1]+1]
        lengths = np.r_[0., np.cumsum(np.linalg.norm(np.diff(patch['vertices'][ids], axis=0), axis=1))]
        require(lengths[-1] > patch['scale']*1e-10, 'BASE_INVALID_CORNERS')
        uv[ids] = rectangle[i]+(lengths/lengths[-1])[:, None]*(rectangle[i+1]-rectangle[i])
    patch['uv'] = harmonic(patch, uv, boundary); signed = chart.determinants(patch['uv'][patch['faces']])
    require(np.all(signed > 1e-12) or np.all(signed < -1e-12), 'BASE_CHART_FOLDED'); return patch


def grid(vertices, triangles, spec):
    if 'grid_vertex_ids' in spec:
        ids = np.asarray(spec['grid_vertex_ids'], int)
        require(ids.ndim == 2 and min(ids.shape) >= 4 and max(ids.shape) <= 129, 'BASE_INVALID_GRID')
        require(ids.min() >= 0 and ids.max() < len(vertices), 'BASE_INVALID_GRID'); return vertices[ids]
    ids = spec['source_triangles']; corners = spec['boundary_vertex_ids']
    require(min(ids) >= 0 and max(ids) < len(triangles) and len(set(ids)) == len(ids), 'BASE_INVALID_SELECTION')
    require(min(corners) >= 0 and max(corners) < len(vertices), 'BASE_INVALID_CORNERS')
    patch = mesh(list(vertices[triangles[ids]]))
    patch = parameterize(patch, chart.landmark_vertices(patch, vertices[corners]))
    return chart.sample(patch, coordinates(17, 49), Budget()).reshape(17, 49, 3)
