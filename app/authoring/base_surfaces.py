"""Read-only, journaled preparation of head-aware underside surface patches."""
import numpy as np
from ...core.authoring.base_structure import prepare
from ...core.authoring.errors import require
from ...core.authoring.transfer_meshes import world
from .transfers import capture
from .transfers import key
from ...core.authoring.codec import digest


def serial(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: serial(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(v) for v in value]
    return value


def spatial_check(service, result):
    check = getattr(service.scene, 'base_mesh_quality', None)
    require(callable(check), 'UNSUPPORTED_CAPABILITY', 'Base surface spatial inspection is unavailable.')
    result['spatial_quality'] = check(result['vertices'], result['triangles'])
    if result['spatial_quality']['nonadjacent_bvh_overlap_pairs']:
        result['status'] = 'unresolved'
    return serial(result)


def prepare_base(service, request):
    params = request['params']; service.check(params); row = capture(service, [params['source_object']])[params['source_object']]
    require(row['topology_digest'] == params['topology_digest'], 'STALE_BASE_TOPOLOGY')
    require(row['geometry_digest'] == params['geometry_digest'], 'STALE_BASE_GEOMETRY')
    definition = {k: params[k] for k in ('heads', 'arcs', 'patches')}; definition['settings'] = params.get('settings', {})
    definition.update(vertices=world(row['geometry']), triangles=row['geometry']['triangles'])
    result = spatial_check(service, prepare(definition)); result['source'] = {k: params[k] for k in ('source_object', 'topology_digest', 'geometry_digest')}
    result['id'] = digest(result); service.store.put('base_previews', key(service, result['id']), result)
    asset = service.store.asset(result, 'muscle_base_preview'); summary = {k: result[k] for k in ('version', 'status', 'heads', 'connections', 'topology', 'spatial_quality', 'limitations')}
    summary['id'] = result['id']; summary['patches'] = [dict(id=p['id'], head_ids=p['head_ids'], quality=p['quality']) for p in result['patches']]
    diagnostics = [] if result['status'] == 'geometry_candidate' else [dict(code='BASE_CHART_UNRESOLVED', severity='error', message='Patch geometry or assembly needs correction before curve generation.')]
    return dict(status='success' if not diagnostics else 'unresolved', assets=[asset], base_surface=summary, diagnostics=diagnostics)
