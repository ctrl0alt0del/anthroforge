"""Reference-pose coordinate frames and explicit anatomical bindings."""
import numpy as np
from .errors import require
from .codec import digest
from .references import lookup
from .model import Registry


def binding(document, inventory, reference):
    spec = lookup(document, reference)
    require(spec.get('instance_id'), 'BINDING_UNBOUND', reference)
    matches = [v for v in inventory['instances'] if v['instance_id'] == spec['instance_id']]
    require(len(matches) == 1, 'BINDING_AMBIGUOUS' if matches else 'BINDING_STALE', reference)
    require(matches[0]['scp_id'] == spec['scp_id'], 'BINDING_OWNER_MISMATCH', reference)
    return matches[0]


def frame(document, inventory, reference, registry=None, active=()):
    spec = frame_spec(document, inventory, reference, active)
    owner = binding(document, inventory, spec['owner'])
    geometry = inventory['geometry'].get(owner['instance_id'])
    require(geometry is not None, 'SURFACE_DOMAIN_UNAVAILABLE', reference)
    return (registry or coordinate_resolvers()).get(spec['kind']+'.v1')(spec, owner, geometry)


def frame_spec(document, inventory, reference, active=()):
    require(reference not in active, 'FRAME_DEPENDENCY_CYCLE')
    spec = lookup(document, reference)
    if spec['kind'] == 'box':
        return spec
    from .landmark_frames import resolve_axes
    return dict(spec, axes=resolve_axes(document, inventory, spec, active+(reference,)))


def box_frame(spec, owner, geometry):
    axes = np.asarray(spec['axes'], dtype=float)
    require(np.allclose(axes @ axes.T, np.eye(3), atol=1e-6), 'FRAME_AXES_INVALID')
    local = np.asarray(geometry['vertices']) @ axes.T
    low, high = local.min(axis=0), local.max(axis=0)
    require(np.all(high-low > 1e-10), 'FRAME_DEGENERATE')
    matrix = valid_matrix(geometry['matrix'])
    linear = matrix[:3, :3] @ axes.T @ np.diag(high-low)
    return dict(origin=matrix[:3, :3] @ (axes.T @ low)+matrix[:3, 3], linear=linear, owner=owner, geometry=geometry)


def coordinate_resolvers():
    registry = Registry()
    registry.add('box.v1', box_frame)
    registry.add('landmark_box.v1', box_frame)
    return registry


def valid_matrix(value):
    matrix = np.asarray(value)
    require(abs(np.linalg.det(matrix[:3, :3])) > 1e-12, 'FRAME_DEGENERATE')
    return matrix


def world(chart, q):
    return np.asarray(q) @ chart['linear'].T + chart['origin']


def coordinates(chart, points):
    return (np.asarray(points)-chart['origin']) @ np.linalg.inv(chart['linear']).T


def surface(chart):
    geometry = chart['geometry']
    vertices, matrix = np.asarray(geometry['vertices']), np.asarray(geometry['matrix'])
    points = vertices @ matrix[:3, :3].T+matrix[:3, 3]
    return coordinates(chart, points)[np.asarray(geometry['triangles'], dtype=int)]


def control(document, inventory, reference):
    spec = lookup(document, reference)
    rows = [c for c in inventory['controls'] if c['instance_id'] == spec['instance_id']]
    require(len(rows) == 1, 'CONTROL_UNAVAILABLE')
    validate_control(spec, rows[0])
    require(rows[0]['kind'] == spec['kind'], 'CONTROL_KIND_MISMATCH')
    return dict(rows[0], reference_points=spec.get('reference_points', rows[0].get('points', [])))


def validate_control(spec, row):
    require(row.get('supported', True), 'UNSUPPORTED_CONTROL_REPRESENTATION')
    if row['digest'] == spec['reference_digest']:
        return
    before, after = np.asarray(spec.get('reference_points', [])), np.asarray(row.get('points', []))
    require(spec['kind'] == 'guide' and len(before) == len(after) and len(before) > 1, 'CONTROL_REBIND_REQUIRED')
    require((before[-1]-before[0]) @ (after[-1]-after[0]) > 0, 'CONTROL_REBIND_REQUIRED')


def guide_position(row, t):
    points, reference = np.asarray(row['points']), np.asarray(row['reference_points'])
    lengths = np.linalg.norm(np.diff(reference, axis=0), axis=1)
    require(np.all(lengths > 1e-10) and 0 <= t <= 1, 'GUIDE_DEGENERATE')
    s = np.r_[0., np.cumsum(lengths)]/sum(lengths)
    return np.array([np.interp(t, s, points[:, axis]) for axis in range(3)])


def guide_material(points, point, reference=None):
    points = np.asarray(points)
    edges = np.diff(points, axis=0)
    lengths = np.linalg.norm(edges, axis=1)
    require(len(lengths) > 0 and np.all(lengths > 1e-10), 'GUIDE_DEGENERATE')
    t = np.clip(np.sum((point-points[:-1])*edges, axis=1)/(lengths**2), 0, 1)
    distances = np.linalg.norm(points[:-1]+t[:, None]*edges-point, axis=1)
    index = int(np.argmin(distances))
    lengths = np.linalg.norm(np.diff(reference, axis=0), axis=1) if reference is not None else lengths
    return float((sum(lengths[:index])+t[index]*lengths[index])/sum(lengths)), float(distances[index])
