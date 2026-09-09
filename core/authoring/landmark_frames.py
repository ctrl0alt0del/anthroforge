"""Landmark-defined orthonormal owner frames without mesh vertex addresses."""
import numpy as np
from .errors import require
from .references import lookup
from .substrate import frame, world, binding, valid_matrix


def resolve_axes(document, inventory, specification, active=()):
    owner = binding(document, inventory, specification['owner'])
    matrix = valid_matrix(inventory['geometry'][owner['instance_id']]['matrix'])
    landmarks = [lookup(document, specification[k]) for k in ('origin', 'axis_point', 'plane_point')]
    charts = [frame(document, inventory, p['frame'], active=active) for p in landmarks]
    require(all(c['owner']['instance_id'] == owner['instance_id'] for c in charts), 'LANDMARK_OWNER_MISMATCH')
    points = np.array([world(c, p['q']) for c, p in zip(charts, landmarks)])
    local = (points-matrix[:3, 3]) @ np.linalg.inv(matrix[:3, :3]).T
    x = unit(local[1]-local[0])
    z = unit(np.cross(x, local[2]-local[0]))
    return np.array([x, np.cross(z, x), z]).tolist()


def unit(value):
    length = np.linalg.norm(value)
    require(length > 1e-10, 'LANDMARK_FRAME_DEGENERATE')
    return value/length
