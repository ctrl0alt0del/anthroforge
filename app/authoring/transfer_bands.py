"""Qualify explicit attachment targets independently of skeletal RBF landmarks."""
import numpy as np
from ...core.authoring.errors import require
from ...core.authoring.indexed_patches import topology
from ...core.authoring.transfer_meshes import world
from ...core.authoring.transfer_band_mapping import project
from .transfer_bindings import target_domain, target_point


def source_indices(rows, names, band):
    name = band['source_object']; require(name in names, 'TRANSFER_SHAPE_BAND_SOURCE')
    row = rows[name]; ids = np.asarray(band['vertex_indices'], dtype=np.int64)
    require(row['topology_digest'] == band['topology_digest'], 'TRANSFER_SOURCE_TOPOLOGY_CHANGED')
    require(row['geometry_digest'] == band['geometry_digest'], 'STALE_TRANSFER_SOURCE')
    require(len(set(ids)) == len(ids) and ((ids >= 0) & (ids < len(row['geometry']['vertices']))).all(), 'TRANSFER_SHAPE_INDEX')
    return ids, world(row['geometry'])[ids]


def destination(service, band, spec, cache):
    target = band['target']; domain = target_domain(service, target, cache)
    require(domain['owner'] in spec['obstacle_instance_ids'], 'TRANSFER_BAND_TARGET_OBSTACLE')
    geometry = service.inventory['geometry'][domain['owner']]
    require(topology(geometry) == target['topology_digest'], 'TRANSFER_TARGET_TOPOLOGY_CHANGED')
    require(bool(domain['polygons']), 'TRANSFER_REGION_EMPTY')
    return domain


def targets(service, band, vertices, domain, cache):
    if 'mapping' in band:
        return project(vertices, domain['polygons'], band['mapping'])
    bindings = band['target_bindings']
    require(len(bindings) == len(vertices), 'TRANSFER_BAND_TARGET_COUNT')
    points = [target_point(service, dict(band['target'], surface_binding=b), cache)['point'] for b in bindings]
    return np.asarray(points), dict(method='indexed_target_bindings.v1', max_projection_distance=0.)


def resolve(service, rows, names, spec):
    output, cache, labels = [], {}, set()
    seen = {(b['source_object'], int(i)) for b in spec['protected_bands'] for i in b['vertex_indices']}
    for band in spec.get('attachment_bands', []):
        require(band['id'] not in labels, 'TRANSFER_BAND_ID_DUPLICATED'); labels.add(band['id'])
        ids, vertices = source_indices(rows, names, band); name = band['source_object']
        keys = {(name, int(i)) for i in ids}; require(not keys & seen, 'TRANSFER_BAND_OVERLAP'); seen.update(keys)
        domain = destination(service, band, spec, cache); points, report = targets(service, band, vertices, domain, cache)
        output.append(dict(id=band['id'], source_object=name, vertex_indices=ids.tolist(), targets=points.tolist(),
            target_owner=domain['owner'], region=band['target']['region'], region_digest=domain['definition_digest'], **report))
    return output


def verify(service, record):
    spec = record['definition']['shape_preservation']; cache = {}
    old = record['result']['shape_preservation'].get('attachment_bands', [])
    for band, saved in zip(spec.get('attachment_bands', []), old):
        domain = destination(service, band, spec, cache)
        require(domain['definition_digest'] == saved['region_digest'], 'STALE_TRANSFER_TARGET')


def configure(service, rows, names, spec):
    resolved = resolve(service, rows, names, spec)
    return dict(spec, _attachment_targets=resolved), resolved


def validate_domains(service, params):
    spec = params.get('shape_preservation', {}); cache = {}
    for band in spec.get('attachment_bands', []):
        destination(service, band, spec, cache)
