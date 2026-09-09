"""Exact first-hit picking with explicit section and owner semantics."""
import numpy as np
from .geometry import ray_hits, normalized
from .codec import digest
from . import visual_camera as camera, visual_mesh as mesh


def pick(scene, view, uv):
    triangles, identities = mesh.triangles(scene)
    origin, direction, distance = camera.ray(view['camera'], uv, triangles)
    hits = sorted(ray_hits(triangles, origin, direction, distance), key=lambda row: (round(row[0], 10), row[1]))
    section = view.get('section')
    hits = [h for h in hits if not section or np.dot(h[2], section['normal']) <= section['distance']+1e-10]
    if not hits:
        return dict(hit=False, uv=uv, reason='BACKGROUND')
    _, index, point = hits[0]
    owner, face = identities[index]
    normal = normalized(np.cross(triangles[index, 1]-triangles[index, 0], triangles[index, 2]-triangles[index, 0]))
    result = dict(hit=True, uv=uv, owner=owner, triangle=face, barycentric=mesh.barycentric(triangles[index], point).tolist(), point=point.tolist(), normal=normal.tolist(), on_requested_owner=owner == scene['owner'])
    result.update(snapshot_id=view['snapshot_id'], scene_revision=scene['scene_revision'], view_id=view['id'], topology_digest=mesh.topology(scene['geometry'][owner]), pixel_world_size=view['camera']['span']/view['camera']['width'], incidence=abs(float(normal @ direction)))
    return dict(result, id=digest(result))


def project_hit(scene, view, hit):
    point = np.asarray(hit['point'])
    projected = camera.project(view['camera'], point)
    uv = projected[:2].tolist()
    if min(uv) < 0 or max(uv) > 1:
        return dict(point_id=hit['id'], uv=uv, state='outside_view')
    other = pick(scene, view, uv)
    tolerance = view['camera']['span']*1e-7
    visible = other['hit'] and other['owner'] == hit['owner'] and np.linalg.norm(np.asarray(other['point'])-point) < tolerance
    return dict(point_id=hit['id'], uv=uv, state='visible' if visible else 'occluded')


def markers(pixels, rows):
    result = pixels.copy()
    height, width = result.shape[:2]
    yy, xx = np.mgrid[:height, :width]
    for row in rows:
        if row['state'] != 'visible':
            continue
        x, y = np.asarray(row['uv'])*[width, height]-.5
        radius = (xx-x)**2+(yy-y)**2
        result[(radius >= 16) & (radius <= 36)] = [255, 187, 65]
        result[radius <= 2] = [255, 239, 177]
    return result
