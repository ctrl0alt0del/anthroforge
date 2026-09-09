"""Detached inspection geometry and stable references within one snapshot."""
import numpy as np
from .codec import digest
from .errors import require
from .visual_camera import vertices
from .clipping import plane, triangulate


def snapshot(inventory, owner, context=()):
    require(owner in inventory['geometry'], 'SURFACE_DOMAIN_UNAVAILABLE', owner)
    keys = [owner]+sorted(set(context)-{owner})
    require(set(keys) <= set(inventory['geometry']), 'VIEW_CONTEXT_UNAVAILABLE')
    controls = [c for c in inventory['controls'] if c.get('scp_id') in {r['scp_id'] for r in inventory['instances'] if r.get('instance_id') in keys}]
    return dict(root_id=inventory['root_id'] or inventory['scene_id'], scene_revision=inventory['revision'], reference_pose=inventory['reference_pose'], owner=owner, geometry={k: inventory['geometry'][k] for k in keys}, controls=controls)


def triangles(scene):
    parts, identities = [], []
    for owner, geometry in scene['geometry'].items():
        faces = np.asarray(geometry['triangles'], dtype=int)
        require(faces.ndim == 2 and faces.shape[1] == 3, 'VIEW_TRIANGLES_INVALID')
        parts.append(vertices(geometry)[faces])
        identities.extend((owner, i) for i in range(len(faces)))
    return np.concatenate(parts), identities


def topology(geometry):
    return digest([len(geometry['vertices']), geometry['triangles']])


def barycentric(triangle, points):
    a, b, c = triangle
    uv = np.linalg.lstsq(np.array([b-a, c-a]).T, (np.asarray(points)-a).T, rcond=None)[0].T
    return np.concatenate([1-uv.sum(axis=-1, keepdims=True), uv], axis=-1)


def clipped(triangle, section):
    if not section:
        return [triangle]
    polygon = plane(triangle, np.asarray(section['normal']), section['distance'])
    return triangulate([polygon])


def section_valid(section):
    if section:
        require(np.linalg.norm(section['normal']) > 1e-10, 'VIEW_SECTION_INVALID')
    return section


def current(scene, inventory):
    if scene['reference_pose'] != inventory['reference_pose']:
        return False
    controls = {c['instance_id']: c['digest'] for c in inventory['controls']}
    stable = all(controls.get(c['instance_id']) == c['digest'] for c in scene.get('controls', []))
    return stable and all(digest(value) == digest(inventory['geometry'].get(key)) for key, value in scene['geometry'].items())


def compatible(first, second, owner):
    if not first or not second or owner not in first['geometry'] or owner not in second['geometry']:
        return False
    return first['root_id'] == second['root_id'] and first['reference_pose'] == second['reference_pose'] and digest(first['geometry'][owner]) == digest(second['geometry'][owner])
