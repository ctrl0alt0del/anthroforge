"""Conservative automatic neighborhoods and one snapshot-bound measurement packet."""
import numpy as np
from .visual_camera import vertices, orientation
from .errors import require
from .codec import digest


def bounds(geometry):
    points = vertices(geometry)
    require(len(points) > 0 and np.isfinite(points).all(), 'VIEW_GEOMETRY_INVALID')
    return np.array([points.min(0), points.max(0)])


def box_gap(first, second):
    separation = np.maximum(np.maximum(first[0]-second[1], second[0]-first[1]), 0)
    return float(np.linalg.norm(separation))


def context(inventory, owner, params):
    require(owner in inventory['geometry'], 'SURFACE_DOMAIN_UNAVAILABLE', owner)
    boxes = {key: bounds(value) for key, value in inventory['geometry'].items()}
    radius = params.get('neighbor_distance', float(np.linalg.norm(np.ptp(boxes[owner], axis=0)))*.15)
    require(np.isfinite(radius) and radius >= 0, 'VIEW_NEIGHBOR_DISTANCE_INVALID')
    automatic = params.get('automatic_context', 'context_ids' not in params)
    explicit = set(params.get('context_ids', []))-{owner}
    require(explicit <= set(boxes), 'VIEW_CONTEXT_UNAVAILABLE')
    gaps = {key: box_gap(boxes[owner], value) for key, value in boxes.items() if key != owner}
    included = sorted(explicit | {key for key, gap in gaps.items() if automatic and gap <= radius})
    rows = [dict(instance_id=key, aabb_gap=gaps[key], reason='explicit' if key in explicit else 'automatic_aabb') for key in included]
    return included, dict(automatic=automatic, distance=radius, units='scene', candidates=rows,
                          method='Conservative world AABB proximity; overlapping boxes are not proof of mesh collision.')


def measurements(geometry):
    points, faces = vertices(geometry), np.asarray(geometry['triangles'], dtype=int)
    triangles = points[faces]
    areas = np.linalg.norm(np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]), axis=1)*.5
    center = np.average(triangles.mean(1), axis=0, weights=areas) if areas.sum() > 0 else points.mean(0)
    box = np.array([points.min(0), points.max(0)])
    return dict(world_bounds=box.tolist(), world_extents=np.ptp(box, axis=0).tolist(),
                surface_area=float(areas.sum()), surface_centroid=center.tolist(),
                vertex_count=len(points), triangle_count=len(faces), object_axes=orientation(geometry).tolist(),
                matrix=geometry['matrix'], geometry_digest=digest(geometry))


def packet(scene, selection, inventory):
    from .visual_labels import identity
    names = {row['instance_id']: row.get('locator', row['instance_id']) for row in inventory['instances']}
    objects = [dict(instance_id=key, name=names.get(key, key), label=identity(key, 'O'), **measurements(value))
               for key, value in scene['geometry'].items()]
    return dict(snapshot_id=digest(scene), scene_revision=scene['scene_revision'], owner=scene['owner'],
                units=dict(length='scene', area='scene_squared'), neighborhood=selection, objects=objects,
                limitations=['Object axes are not reviewed anatomical axes.', 'No anatomical or collision acceptance inferred.'])
