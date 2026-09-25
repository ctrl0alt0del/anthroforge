"""Resolve protected indexed bands and obstacle snapshots for opt-in transfer."""
import numpy as np
from ...core.authoring.codec import digest
from ...core.authoring.errors import require


def supports(service, spec):
    ids = spec['obstacle_instance_ids']; available = service.inventory['geometry']
    require(len(ids) == len(set(ids)) and set(ids) <= set(available), 'TRANSFER_SHAPE_OBSTACLES')
    return {identity: available[identity] for identity in ids}


def bands(rows, names, spec):
    masks = {name: np.zeros(len(rows[name]['geometry']['vertices']), dtype=np.int32) for name in names}
    for band in spec['protected_bands']:
        name = band['source_object']; require(name in masks, 'TRANSFER_SHAPE_BAND_SOURCE')
        require(rows[name]['topology_digest'] == band['topology_digest'], 'TRANSFER_SOURCE_TOPOLOGY_CHANGED')
        require(rows[name]['geometry_digest'] == band['geometry_digest'], 'STALE_TRANSFER_SOURCE')
        indices = band['vertex_indices']; require(all(0 <= i < len(masks[name]) for i in indices), 'TRANSFER_SHAPE_INDEX')
        masks[name][np.asarray(indices, dtype=np.int64)] = 1
    require(all(m.any() for m in masks.values()), 'TRANSFER_SHAPE_MISSING_PART_BAND', 'Supply attachment bands for every selected head.')
    return masks


def apply(service, params, rows, result):
    if 'shape_preservation' not in params:
        return result
    spec = params['shape_preservation']; geometry = supports(service, spec)
    require(all(np.isfinite(v) for v in spec.get('settings', {}).values()) and np.isfinite(spec['tolerance']), 'TRANSFER_SHAPE_SETTINGS')
    masks = bands(rows, params['source_objects'], spec)
    method = getattr(service.scene, 'shape_transfer', None)
    require(callable(method), 'UNSUPPORTED_CAPABILITY', 'Shape transfer requires the native scene adapter.')
    output = method(rows, result, geometry, masks, spec)
    output['shape_preservation']['support_digest'] = digest(geometry)
    return output


def verify(service, record):
    spec = record['definition'].get('shape_preservation')
    if spec:
        require(digest(supports(service, spec)) == record['result']['shape_preservation']['support_digest'], 'STALE_TRANSFER_OBSTACLES')
