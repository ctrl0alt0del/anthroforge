"""Accurate native bindings retain the sampled face normal at mesh creases."""
import numpy as np
from .errors import require
from .geometry import face_normals
from .nearest import nearest
from .visual_mesh import barycentric


def capture(geometry, point, normal):
    matrix = np.asarray(geometry['matrix']); faces = np.asarray(geometry['triangles'], dtype=int)
    vertices = np.asarray(geometry['vertices']) @ matrix[:3, :3].T + matrix[:3, 3]
    triangles = vertices[faces]
    normals = face_normals(triangles)
    normals *= np.sign(np.linalg.det(matrix[:3, :3]))
    candidates = np.flatnonzero(normals @ np.asarray(normal) > 1-1e-6)
    require(len(candidates) > 0, 'ATTACHMENT_NORMAL_UNRESOLVED')
    closest, index = nearest(triangles[candidates], np.asarray(point))
    require(np.linalg.norm(closest-point) <= 1e-5, 'ATTACHMENT_CAPTURE_FAILED')
    triangle = int(candidates[index]); weights = barycentric(triangles[triangle], closest)
    return dict(tri_vidx=faces[triangle].tolist(), tri_weights=weights.tolist())


def resolve(geometry, binding):
    matrix, faces = np.asarray(geometry['matrix']), np.asarray(geometry['triangles'], dtype=int)
    indices, weights = np.asarray(binding['tri_vidx'], dtype=int), np.asarray(binding['tri_weights'], dtype=float)
    require(indices.shape == weights.shape == (3,) and np.isfinite(weights).all(), 'ATTACHMENT_BINDING_INVALID')
    require(np.all(weights >= -1e-8) and np.all(weights <= 1+1e-8) and abs(weights.sum()-1) < 1e-8, 'ATTACHMENT_BINDING_INVALID')
    require(np.any(np.all(faces == indices, axis=1)), 'ATTACHMENT_TOPOLOGY_CHANGED')
    vertices = np.asarray(geometry['vertices'])[indices] @ matrix[:3, :3].T + matrix[:3, 3]
    normal = face_normals(vertices[None])[0] * np.sign(np.linalg.det(matrix[:3, :3]))
    require(np.linalg.norm(normal) > .5, 'ATTACHMENT_FACE_DEGENERATE')
    return weights @ vertices, normal
