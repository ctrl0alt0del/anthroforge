"""Explicit section measurements and supported planar boundary closure."""
import numpy as np
from .errors import require
from .clipping import area, triangulate


def sections(output):
    if 'side_a' in output: return envelope_sections(output)
    grid = np.array(output['inflated']).reshape((len(output['u']), len(output['s']), 3))
    base = np.array(output['base']).reshape(grid.shape)
    return [section(grid[:, i], base[:, i], float(s)) for i, s in enumerate(output['s'])]


def section(points, base, s):
    across = base[-1]-base[0]
    length = np.linalg.norm(across)
    require(length > 1e-12, 'SECTION_DEGENERATE')
    coordinates = points @ (across/length)
    return dict(s=s, width=float(np.ptp(coordinates)), height=float(np.linalg.norm(points-base, axis=1).max()), points=points.tolist())


def closure(output, kind):
    require(kind == 'planar_caps', 'CLOSURE_REQUIRED')
    points = np.array(output['inflated'])
    faces = output.get('inflated_faces', output['faces'])
    edges = boundary_edges(faces)
    loops = boundary_loops(edges)
    triangles = triangulate([points[face] for face in faces])
    for loop in loops:
        triangles.extend(cap(points[list(reversed(loop))], max(np.ptp(points, axis=0))))
    volume = abs(sum(np.dot(a, np.cross(b, c))/6 for a, b, c in triangles))
    return dict(area=sum(area(t) for t in triangles), volume=float(volume))


def cap(polygon, scale):
    normal = np.linalg.svd(polygon-polygon.mean(axis=0))[2][-1]
    require(np.max(abs((polygon-polygon[0]) @ normal)) <= 1e-6*scale, 'NONPLANAR_CLOSURE_UNSUPPORTED')
    edges = np.roll(polygon, -1, axis=0)-polygon
    turns = np.cross(edges, np.roll(edges, -1, axis=0)) @ normal
    require(not (np.any(turns > 1e-10*scale**2) and np.any(turns < -1e-10*scale**2)), 'CONCAVE_CLOSURE_UNSUPPORTED')
    return triangulate([polygon])


def boundary_edges(faces):
    counts = {}
    for face in faces:
        for a, b in zip(face, face[1:]+face[:1]):
            key = tuple(sorted((a, b)))
            counts.setdefault(key, []).append((a, b))
    require(all(len(v) <= 2 for v in counts.values()), 'NONMANIFOLD_CLOSURE_UNSUPPORTED')
    return [v[0] for v in counts.values() if len(v) == 1]


def boundary_loops(edges):
    remaining, result = dict(edges), []
    require(len(remaining) == len(edges), 'AMBIGUOUS_BOUNDARY')
    while remaining:
        start = next(iter(remaining))
        loop, current = [], start
        while current in remaining:
            loop.append(current)
            current = remaining.pop(current)
        require(current == start and len(loop) >= 3, 'OPEN_BOUNDARY')
        result.append(loop)
    return result


def envelope_sections(output):
    shape = (len(output['u']), len(output['s']), 3)
    a, b, base = (np.asarray(output[key]).reshape(shape) for key in ('side_a', 'side_b', 'base'))
    return [envelope_section(a[:, i], b[:, i], base[:, i], float(s)) for i, s in enumerate(output['s'])]


def envelope_section(a, b, base, s):
    combined = section(np.vstack((a, b)), np.vstack((base, base)), s)
    return dict(s=s, side_a=section(a, base, s), side_b=section(b, base, s), width=combined['width'],
                max_material_span=float(np.linalg.norm(a-b, axis=1).max()))
