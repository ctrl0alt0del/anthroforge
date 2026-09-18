"""Union repair and underside evidence preceding explicit anatomical selection."""
from ...core.authoring.codec import digest
from ...core.authoring.errors import require
from ...core.authoring.transfer_meshes import fingerprint
from .base_definitions import source
from .transfers import key


def base_candidates(service, request):
    params = request['params']; service.check(params); row = source(service, params)
    owners = params['support_instances']; require(set(owners) <= set(service.inventory['geometry']), 'BASE_UNKNOWN_SUPPORT')
    result = service.scene.base_candidates(row, {o: service.inventory['geometry'][o] for o in owners})
    result['source'] = {k: params[k] for k in ('source_object', 'topology_digest', 'geometry_digest')}
    result['support_digest'] = digest({o: service.inventory['geometry'][o] for o in owners})
    return dict(base_surface=dict(candidate_triangle_count=len(result['source_triangles']), anatomical_review='required'),
                assets=[service.store.asset(result, 'underside_evidence')])


def repair_volume(service, request):
    params = request['params']; service.check(params); names = [s['source_object'] for s in params['sources']]
    require(len(set(names)) == len(names), 'BASE_DUPLICATE_SOURCE')
    rows = {spec['source_object']: source(service, spec) for spec in params['sources']}
    identity = digest(['volume_union.v1', fingerprint(rows)]); record = service.store.get('volume_unions', key(service, identity))
    if record is None:
        result = service.scene.union_volume(rows); record = union_record(identity, params, rows, result)
        service.store.put('volume_unions', key(service, identity), record)
    if record['result']['status'] != 'success':
        return dict(status='unresolved', base_surface=record['result']['meshes'][0]['quality'], assets=[service.store.asset(record, 'unresolved_union')],
                    diagnostics=[dict(code='BASE_UNION_UNRESOLVED', severity='error', message='Exact union still has open/nonmanifold edges or detected overlaps. Repair this reference before selecting its underside.')])
    with service.scene.publish_transfer(record) as published:
        response = dict(published=True, transfer=dict(union_id=identity, **published))
        service.store.put('volume_union_receipts', key(service, identity), response)
    return response


def union_record(identity, params, rows, result):
    row = dict(result, source_object='Union_'+identity[:12], color=next(iter(rows.values()))['color'])
    status = 'success' if result['quality']['ready'] else 'unresolved'
    output = dict(version='volume_union.v1', method='blender_exact_self_union.v1', meshes=[row], status=status,
                  field={}, annotations=[], validation=dict(anatomy='not_evaluated', volume='closed_edges_and_bvh_only'))
    return dict(id=identity, definition=params, source_fingerprint=fingerprint(rows), result=output)
