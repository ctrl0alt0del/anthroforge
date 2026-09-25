"""Explicit adjacent-head repairs and optional smooth-base construction hook."""
from copy import deepcopy
from ...core.authoring.base_partition import calculate, native_mesh
from ...core.authoring.codec import digest
from ...core.authoring.errors import require
from .base_surfaces import serial
from .transfers import key
from ...core.authoring.partition_assembly import connection, meshes


def preview(service, request):
    params = request['params']; service.check(params)
    result = calculate(params['paths'], params['sides'], params['settings'])
    result['connection'] = connection(params['paths'], result, params.get('connection'))
    result['meshes'] = meshes(result)
    quality = service.scene.partition_base_quality(result['meshes'])
    result.update(version='base_partition.v1', quality=quality, definition=params)
    result = serial(result); result['id'] = digest(result)
    service.store.put('base_partitions', key(service, result['id']), result)
    return dict(status='success' if quality['ready'] else 'unresolved', partition={k: v for k, v in result.items() if k not in ('paths', 'stations', 'meshes', 'definition')},
        assets=[service.store.asset(result, 'base_partition')], diagnostics=[] if quality['ready'] else [dict(code='PARTITION_ASSEMBLY_UNRESOLVED', severity='error', message='The repaired assembly still has crossings or collapsed triangles.')])


def apply(service, parts, params):
    output = deepcopy(parts); occupied = set(); lookup = {p['id']: p for p in output}
    for spec in params.get('overlap_repairs', []):
        names = spec['patch_ids']; require(len(set(names)) == 2 and set(names) <= set(lookup), 'PARTITION_INVALID_PAIR')
        require(not occupied.intersection(names), 'PARTITION_REPEATED_PATCH'); occupied.update(names)
        pair = [lookup[name] for name in names]
        require(all(sum(f['key'] == other['key'] for p in parts for other in p['fibers']) == 1 for part in pair for f in part['fibers']), 'PARTITION_SHARED_FIBER_CONFLICT')
        result = calculate([[f['path'] for f in p['fibers']] for p in pair], spec['sides'], spec['settings'])
        if not result['changed']: continue
        for part, paths, stations in zip(pair, result.pop('paths'), result.pop('stations')):
            replace(part, paths, stations, result)
    return output


def replace(part, paths, stations, report):
    for fiber, path, values in zip(part['fibers'], paths, stations):
        require(fiber['path'][0] == path[0] and fiber['path'][-1] == path[-1], 'PARTITION_ENDPOINT_CHANGED')
        fiber.update(path=path, stations=values)
    part['native'] = native_mesh(paths, stations); part['partition'] = report
    part['pre_partition_base'] = part['base']; part['base'] = deepcopy(part['native'])
    part.update(rows=part['native']['rows'], columns=part['native']['columns'], controls_role='pre_partition_fit_only')


def operations():
    return {'anatomy.partition_base_surfaces': preview}
