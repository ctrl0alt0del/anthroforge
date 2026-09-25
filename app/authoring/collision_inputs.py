"""Resolve versioned source geometry, selected SCPs, bands and contact bindings."""
import numpy as np
from ...core.authoring.attachment_binding import resolve
from ...core.authoring.errors import require
from ...core.authoring.codec import digest
from .base_definitions import source


def inputs(service, params):
    service.check(params); row = source(service, params)
    require(all(np.isfinite(v) for v in params['settings'].values() if isinstance(v, (int, float))), 'COLLISION_SETTINGS_INVALID')
    require(all(np.isfinite(r['center']).all() and np.isfinite(r['radius']) for r in params['settings'].get('influences', [])), 'COLLISION_SETTINGS_INVALID')
    ids = params['obstacle_instance_ids']+params.get('guard_instance_ids', []); available = service.inventory['geometry']
    require(len(ids) == len(set(ids)) and set(ids) <= set(available), 'COLLISION_UNKNOWN_OBSTACLE')
    supports = {identity: available[identity] for identity in ids}
    return row, supports, digest(supports)


def fixed_indices(params, count):
    bands = params.get('protected_bands', []); ids = [i for band in bands for i in band['vertex_indices']]
    require(len({b['id'] for b in bands}) == len(bands), 'CORRECTION_DUPLICATE_BAND')
    require(all(0 <= i < count for i in ids), 'CORRECTION_PROTECTION_INDEX')
    return np.asarray(sorted(set(ids)), dtype=int)


def contact_constraints(params, row, supports):
    result = []
    require(len({c['id'] for c in params.get('contacts', [])}) == len(params.get('contacts', [])), 'CORRECTION_DUPLICATE_CONTACT')
    for contact in params.get('contacts', []):
        owner = contact['obstacle_instance_id']; require(owner in supports, 'CORRECTION_CONTACT_OWNER')
        resolve(row['geometry'], contact['source_binding'])
        target, _normal = resolve(supports[owner], contact['target_binding'])
        binding = contact['source_binding']
        result.append(dict(indices=binding['tri_vidx'], weights=binding['tri_weights'], target=target))
    return result
