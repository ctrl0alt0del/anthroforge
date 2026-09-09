"""NumPy z-buffer rasterization of the same triangles used for picking."""
import numpy as np
from .visual_camera import project
from .visual_mesh import triangles, clipped
from .model import Budget


def render(scene, camera, section=None, budget=None):
    budget = budget or Budget(maximum=200000)
    mesh, identities = triangles(scene)
    shape = camera['height'], camera['width']
    depth, ids = np.full(shape, np.inf), np.full(shape, -1, dtype=np.int32)
    for index, triangle in enumerate(mesh):
        budget.check()
        for fragment in clipped(triangle, section):
            raster_triangle(project(camera, fragment), index, depth, ids)
    return dict(depth=depth, ids=ids, mesh=mesh, identities=identities)


def raster_triangle(triangle, index, depth, ids):
    height, width = ids.shape
    xy = triangle[:, :2]*[width, height]-.5
    low = np.maximum(np.ceil(xy.min(0)).astype(int), 0)
    high = np.minimum(np.floor(xy.max(0)).astype(int), [width-1, height-1])
    if np.any(high < low):
        return
    yy, xx = np.mgrid[low[1]:high[1]+1, low[0]:high[0]+1]
    weights = weights_at(xy, xx, yy)
    if weights is None:
        return
    z = weights @ triangle[:, 2]
    valid = (weights.min(axis=-1) >= -1e-10) & (z < depth[yy, xx]-1e-10)
    depth[yy[valid], xx[valid]], ids[yy[valid], xx[valid]] = z[valid], index


def weights_at(triangle, x, y):
    a, b, c = triangle
    denominator = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
    if abs(denominator) < 1e-14:
        return None
    first = ((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/denominator
    second = ((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/denominator
    return np.stack([first, second, 1-first-second], axis=-1)


def shade(raster, camera, owner):
    mesh, ids = raster['mesh'], raster['ids']
    normals = np.cross(mesh[:, 1]-mesh[:, 0], mesh[:, 2]-mesh[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-15)
    facing = np.sign(normals @ -np.asarray(camera['forward']))
    normals *= np.where(facing == 0, 1, facing)[:, None]
    light = -.75*np.asarray(camera['forward'])+.4*np.asarray(camera['up'])-.3*np.asarray(camera['right'])
    intensity = .27+.73*np.maximum(normals @ (light/np.linalg.norm(light)), 0)
    colors = np.array([[194, 207, 215] if key == owner else [91, 105, 117] for key, _ in raster['identities']])
    colors = np.clip(colors*intensity[:, None], 0, 255).astype(np.uint8)
    image = np.full((*ids.shape, 3), [25, 32, 40], dtype=np.uint8)
    image[ids >= 0] = colors[ids[ids >= 0]]
    return image
