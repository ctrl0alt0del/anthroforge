"""Resolve declared symmetry into the existing axis-aligned native mirror plane."""
import numpy as np
from . import charts
from .errors import require


def mirror_planes(document, snapshot):
    bound = charts.targets(document, snapshot)
    result = {}
    for name, muscle in document['muscles'].items():
        spec = muscle['symmetry']
        if spec['mode'] == 'explicit':
            result[name] = None
            continue
        frame_spec = document['frames'][spec['plane_frame']]
        chart = charts.frame(frame_spec, bound[frame_spec['owner']])
        result[name] = native_plane(chart, spec)
    return result


def native_plane(chart, spec):
    axis = 'xyz'.index(spec['plane_axis'])
    normal = chart['normal'][:, axis]
    normal = normal / np.linalg.norm(normal)
    world_axis = int(np.argmax(np.abs(normal)))
    require(np.allclose(abs(normal), np.eye(3)[world_axis], atol=1e-8, rtol=0), 'UNSUPPORTED_NATIVE_MIRROR_PLANE')
    q = np.full(3, .5)
    q[axis] = spec['plane_coordinate']
    origin = np.zeros(3)
    origin[world_axis] = charts.position(chart, q)[world_axis]
    return dict(axis='XYZ'[world_axis], origin=origin.tolist())
