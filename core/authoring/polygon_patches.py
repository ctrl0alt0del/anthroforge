"""Transfer indexed material patches when Blender changes a polygon's tessellation.

An index-defined convex parameter domain tracks the polygon's ordered vertices.
Clip the saved patch there, then evaluate its weights on the current triangles.
No rest coordinates or world-space boundary points are stored.
"""
from collections import defaultdict
import numpy as np
from .codec import digest
from .errors import require
from .indexed_patches import canonical, resolve_row
from . import clipping, visual_mesh, visual_selection
from .model import Budget


def topology(geometry):
    require('polygons' in geometry, 'SURFACE_PATCH_POLYGONS_REQUIRED')
    return 'vertices-v2:'+digest([len(geometry['vertices']), sorted(canonical(p) for p in geometry['polygons'])])


def polygon_map(geometry):
    result, triangles = defaultdict(list), defaultdict(list)
    for index, face in enumerate(geometry['polygons']):
        result[canonical(face)].append(index)
    for index, polygon in enumerate(geometry['triangle_polygons']):
        triangles[polygon].append(index)
    return result, triangles


def bind(geometry, patches):
    mapping, _ = polygon_map(geometry)
    rows = []
    for row in patches:
        index = geometry['triangle_polygons'][row['triangle']]
        face = list(geometry['polygons'][index])
        rows.append(dict(tri_vidx=list(geometry['triangles'][row['triangle']]), face_vidx=face,
                         occurrence=mapping[canonical(face)].index(index), polygon=row['polygon']))
    return dict(kind='surface_patch', topology_digest=topology(geometry), patches=rows)


def resolve(geometry, query):
    require(topology(geometry) == query['topology_digest'], 'SURFACE_PATCH_REBIND_REQUIRED')
    mapping, triangles = polygon_map(geometry)
    return [piece for row in query['patches'] for piece in resolve_patch(geometry, row, mapping, triangles)]


def resolve_patch(geometry, row, mapping, triangles):
    require('face_vidx' in row and len(set(row['tri_vidx'])) == 3, 'SURFACE_PATCH_INVALID')
    face, occurrence = canonical(row['face_vidx']), row.get('occurrence', 0)
    matches = mapping.get(face, [])
    require(0 <= occurrence < len(matches) and set(row['tri_vidx']) <= set(face), 'SURFACE_PATCH_REBIND_REQUIRED')
    candidates = triangles[matches[occurrence]]
    existing = [i for i in candidates if canonical(geometry['triangles'][i]) == canonical(row['tri_vidx'])]
    if existing:
        return [resolve_row(dict(row, occurrence=0), geometry['triangles'], {canonical(row['tri_vidx']): existing})]
    return transfer(geometry, row, face, candidates)


def transfer(geometry, row, face, candidates):
    angles = np.arange(len(face))*2*np.pi/len(face)
    uv = np.c_[np.cos(angles), np.sin(angles), np.zeros(len(face))]
    weights = np.asarray(row['polygon'])
    require(weights.shape[1] == 3 and np.all(np.isfinite(weights)) and weights.min() >= -1e-7 and np.allclose(weights.sum(1), 1), 'SURFACE_PATCH_INVALID')
    mask = weights @ uv[[face.index(v) for v in row['tri_vidx']]]
    result, budget = [], Budget(maximum=300000)
    for index in candidates:
        triangle = uv[[face.index(v) for v in geometry['triangles'][index]]]
        pieces, _ = clipping.partition([mask], visual_selection.planes(triangle), budget)
        result.extend(dict(triangle=index, polygon=visual_mesh.barycentric(triangle, p).tolist()) for p in pieces if clipping.area(p) > 1e-12)
    return result
