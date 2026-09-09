"""Area-weighted visibility samples and a camera suggestion for unseen triangles."""
import numpy as np
from . import visual_camera as camera, visual_mesh as mesh, visual_raster as raster
from .model import Budget

SAMPLES = np.array([[1/3, 1/3, 1/3], [.6, .2, .2], [.2, .6, .2], [.2, .2, .6]])


def visibility(scene, views):
    triangles, identities = mesh.triangles(scene)
    owner_ids = np.array([i for i, row in enumerate(identities) if row[0] == scene['owner']])
    samples = np.einsum('ij,kjl->kil', SAMPLES, triangles[owner_ids])
    seen, budget = np.zeros(samples.shape[:2], dtype=bool), Budget(milliseconds=60000, maximum=200000)
    for view in views:
        budget.check()
        buffer = raster.render(scene, view['camera'], view['section'], budget)
        seen |= observed(samples, triangles, owner_ids, view, buffer)
    areas = np.linalg.norm(np.cross(triangles[owner_ids, 1]-triangles[owner_ids, 0], triangles[owner_ids, 2]-triangles[owner_ids, 0]), axis=1)/2
    fraction = seen.mean(axis=1)
    return triangles[owner_ids], seen, areas, fraction


def observed(samples, triangles, owner_ids, view, buffer):
    spec = view['camera']
    projected = camera.project(spec, samples)
    xy = np.floor(projected[..., :2]*[spec['width'], spec['height']]).astype(int)
    inside = np.all(xy >= 0, axis=-1) & np.all(xy < [spec['width'], spec['height']], axis=-1)
    xy = np.clip(xy, 0, [spec['width']-1, spec['height']-1])
    ids = buffer['ids'][xy[..., 1], xy[..., 0]]
    same = ids == owner_ids[:, None]
    normals = np.cross(triangles[owner_ids, 1]-triangles[owner_ids, 0], triangles[owner_ids, 2]-triangles[owner_ids, 0])
    facing = abs(normals @ spec['forward'])/np.maximum(np.linalg.norm(normals, axis=1), 1e-15)
    section = view.get('section')
    permitted = samples @ section['normal'] <= section['distance'] if section else np.ones_like(same)
    return same & inside & permitted & (facing[:, None] >= .15)


def report(scene, views):
    triangles, seen, areas, fraction = visibility(scene, views)
    missing = areas*(1-fraction)
    result = dict(method='four_barycentric_samples_per_triangle', samples=int(seen.size), observed_samples=int(seen.sum()), estimated_area_fraction=float(areas @ fraction/max(float(areas.sum()), 1e-15)), unseen_triangles=np.flatnonzero(fraction == 0).tolist(), limitations=['Pixel visibility samples; small features and subpixel occlusion may be missed.', 'Coverage is geometric observation, not anatomical recognition or completeness.'])
    if float(missing.max(initial=0)) > 1e-12:
        index = int(np.argmax(missing))
        result['suggestion'] = suggested(scene, triangles[index], index)
    return result


def suggested(scene, triangle, index):
    matrix = np.asarray(scene['geometry'][scene['owner']]['matrix'])[:3, :3]
    normal = np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])*np.sign(np.linalg.det(matrix))
    direction = camera.orientation(scene['geometry'][scene['owner']]).T @ normal
    direction /= max(float(np.linalg.norm(direction)), 1e-15)
    return dict(triangle=index, center=triangle.mean(0).tolist(), azimuth=float(np.degrees(np.arctan2(direction[1], direction[0]))), elevation=float(np.degrees(np.arcsin(np.clip(direction[2], -1, 1)))), zoom=2, reason='Inspect the largest remaining area weighted by unobserved samples; camera usefulness still requires confirmation.')
