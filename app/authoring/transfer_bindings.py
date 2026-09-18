"""Resolve indexed skeletal correspondence, never infer it from muscle names."""
import numpy as np
from ...core.authoring import attachment_binding, indexed_patches
from ...core.authoring.clipping import point_in_polygon
from ...core.authoring.errors import require
from ...core.authoring.regions import RegionEvaluator
from .queries import resolved_document


def source_point(sources, spec):
    row = sources[spec['object']]
    require(row['topology_digest'] == spec['topology_digest'], 'TRANSFER_SOURCE_TOPOLOGY_CHANGED')
    return attachment_binding.resolve(row['geometry'], spec['surface_binding'])[0].tolist()


def target_domain(service, spec, cache):
    key = (spec['document_id'], spec['expected_draft_revision'], spec['region'])
    if key not in cache:
        record = service.load(spec)
        require(record['draft_revision'] == spec['expected_draft_revision'], 'STALE_DRAFT_REVISION')
        evaluator = RegionEvaluator(resolved_document(service, record), service.inventory)
        cache[key] = evaluator.evaluate(spec['region'])
    return cache[key]


def target_point(service, spec, cache):
    domain = target_domain(service, spec, cache)
    geometry = service.inventory['geometry'][domain['owner']]
    require(indexed_patches.topology(geometry) == spec['topology_digest'], 'TRANSFER_TARGET_TOPOLOGY_CHANGED')
    point, _normal = attachment_binding.resolve(geometry, spec['surface_binding'])
    polygons = [np.asarray(p) for p in domain['polygons']]
    require(bool(polygons), 'TRANSFER_REGION_EMPTY')
    epsilon = max(1e-7, float(np.linalg.norm(np.ptp(np.concatenate(polygons), axis=0)))*1e-7)
    require(any(point_in_polygon(point, p, epsilon) for p in polygons), 'TRANSFER_POINT_OUTSIDE_REGION')
    return dict(point=point.tolist(), owner=domain['owner'], region_digest=domain['definition_digest'])


def resolve(service, params, sources):
    cache, pairs = {}, []
    for row in params['correspondences']:
        target = target_point(service, row['target'], cache)
        pairs.append(dict(id=row['id'], source=source_point(sources, row['source']), target=target['point'],
                          target_owner=target['owner'], target_region_digest=target['region_digest']))
    labels = [row['id'] for row in pairs]
    require(len(labels) == len(set(labels)), 'TRANSFER_LANDMARK_IDS_DUPLICATED')
    annotations = [dict(id=row['id'], label=row['label'], point=source_point(sources, row['source']))
                   for row in params.get('annotations', [])]
    require(len({row['id'] for row in annotations}) == len(annotations), 'TRANSFER_ANNOTATION_IDS_DUPLICATED')
    return pairs, annotations


def names(params):
    rows = params.get('correspondences', []) + params.get('annotations', [])
    selected = params['source_objects']
    require(len(selected) == len(set(selected)), 'TRANSFER_SOURCE_NAMES_DUPLICATED')
    return sorted(set(selected) | {row['source']['object'] for row in rows})
