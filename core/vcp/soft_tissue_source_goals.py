"""Constraint goals follow the regenerated source, without a second host binding."""
from mathutils import Vector


def source_goals(tissue, rest, sample):
    from ..visualization.soft_tissue_build import _attachment_influences
    goals = []
    for attachment in tissue.attachments:
        if attachment.mode == 'FREE': continue
        for index, mode, influence in _attachment_influences(rest, attachment):
            normal = _normal(tissue, rest, sample, index)
            point = Vector(rest.vertices[index]) + normal * float(attachment.normal_offset)
            goals.append((mode, index, tuple(point), float(attachment.strength) * influence))
    return tuple(goals)


def _normal(tissue, rest, sample, index):
    count = len(sample.points)
    if not count: raise ValueError('Constraint source is empty.')
    if tissue.base_domain == 'SURFACE': return Vector(sample.normals[index % count])
    if tissue.base_domain == 'CURVE':
        ring = max(1, len(rest.vertices) // count)
        return Vector(sample.normals[min(count - 1, index // ring)])
    return Vector((0, 0, 1))
