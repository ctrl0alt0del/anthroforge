"""Penalties for bone samples enclosed by the moving reference volume."""
import numpy as np
from mathutils import Vector
from .collision_geometry import Obstacle
from ...core.authoring.visual_mesh import barycentric


class ReverseContacts:
    def __init__(self, vertices, faces, bones, settings):
        self.faces, self.settings = faces, settings; reference = Obstacle('reference', vertices, faces, settings['tolerance'])
        self.groups, self.seeds = [], []
        for bone in bones:
            points = np.vstack((bone.vertices, bone.vertices[bone.faces].mean(axis=1))); distances = reference.distance(points)[0]
            limit = np.minimum(distances, 0)-settings['tolerance']*.1 if bone.identity in settings.get('guard_instance_ids', []) else np.zeros(len(points))
            self.groups.append((points, limit))
            self.seeds.extend(reference.nearest(points[distances < -settings['tolerance']])[0] if np.any(distances < -settings['tolerance']) else [])

    def __call__(self, vertices, basis):
        mesh = Obstacle('moving', vertices, self.faces, self.settings['tolerance']); residuals, jacobians = [], []
        for points, limits in self.groups:
            distances, gradients = mesh.distance(points); active = np.flatnonzero(distances < limits)
            residuals.append((distances[active]-limits[active])*1000)
            jacobians.append(self.derivative(mesh, points[active], gradients[active], basis))
        return np.concatenate(residuals), np.vstack(jacobians)

    def derivative(self, mesh, points, gradients, basis):
        rows = []
        for point, gradient in zip(points, gradients):
            hit, _normal, face, _distance = mesh.tree.find_nearest(Vector(point)); ids = self.faces[face]
            weights = barycentric(mesh.vertices[ids], np.asarray(hit)); influence = weights @ basis[ids]
            rows.append((-influence[:, None]*gradient*1000).ravel())
        return np.asarray(rows).reshape(len(points), basis.shape[1]*3)
