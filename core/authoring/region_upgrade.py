"""Upgrade saved surface patches while their original topology is available."""
from copy import deepcopy
from . import indexed_patches, substrate, reviews
from .errors import require


def query(value, geometry):
    if value['kind'] == 'surface_patch':
        require('polygons' in geometry, 'SURFACE_PATCH_POLYGONS_REQUIRED')
        rows = indexed_patches.resolve(geometry, value)
        return deepcopy(value) if value['topology_digest'].startswith('vertices-v2:') else indexed_patches.bind(geometry, rows)
    result = deepcopy(value)
    if 'operands' in result:
        result['operands'] = [query(child, geometry) for child in result['operands']]
    if 'query' in result:
        result['query'] = query(result['query'], geometry)
    return result


def upgrade(document, inventory):
    result, patches = deepcopy(document), []
    for name, profile in result.get('skeleton_profiles', {}).items():
        for key, region in profile['regions'].items():
            owner = substrate.binding(document, inventory, region['owner'])['instance_id']
            replacement = query(region['query'], inventory['geometry'][owner])
            if replacement != region['query']:
                region['query'] = replacement
                patches.append(dict(op='replace', path=f'/skeleton_profiles/{name}/regions/{key}/query', value=replacement))
    retain_reviews(document, result, inventory, patches)
    return result, patches


def retain_reviews(before, after, inventory, patches):
    for name, row in before.get('reviews', {}).items():
        subject = row['subject']
        if row['input_digest'] != reviews.inputs(before, inventory, subject):
            continue
        updated = reviews.inputs(after, inventory, subject)
        if updated != row['input_digest']:
            after['reviews'][name]['input_digest'] = updated
            patches.append(dict(op='replace', path=f'/reviews/{name}/input_digest', value=updated))
