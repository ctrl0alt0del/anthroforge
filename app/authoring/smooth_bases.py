"""Immutable combined-stage previews and dependency-guarded publication."""
from ...core.authoring.codec import digest
from ...core.authoring.errors import require
from ...core.authoring.smooth_native import fit
from ...core.authoring.smooth_base import construct
from .smooth_inputs import inputs, fit_pins
from .base_surfaces import serial
from .base_definitions import source
from .transfers import key
from .base_partitions import apply as partition


def preview(service, request):
    params = request['params']; service.check(params)
    grids, seams, aliases, hits = inputs(service, params)
    controls = fit(grids, fit_pins(params['patches'], grids, hits, aliases), seams, params['settings'], [len(p['endpoints']) for p in params['patches']])
    parts = partition(service, construct(grids, controls, params['patches'], aliases, hits, params['settings']), params)
    quality = service.scene.smooth_base_quality(parts, params['seams'], params['settings'])
    result = dict(version='smooth_native_base.v1', definition=params, parts=parts, quality=quality,
        support_digest=digest(service.inventory['geometry']), scene_revision=service.inventory['revision'])
    result = serial(result); result['id'] = digest(result)
    service.store.put('smooth_base_previews', key(service, result['id']), result)
    return dict(status='success' if quality['ready'] else 'unresolved', base_surface=summary(result),
        assets=[service.store.asset(result, 'smooth_native_base')], diagnostics=diagnostics(result))


def summary(result):
    return dict(id=result['id'], version=result['version'], family=result['definition']['family'], quality=result['quality'],
        unique_fibers=len({tuple(f['key']) for p in result['parts'] for f in p['fibers']}),
        parts=[dict(id=p['id'], head_ids=p['head_ids'], fiber_count=len(p['fibers'])) for p in result['parts']],
        representation='coordinated native lofts sharing complete boundary fibers', inflation_fitted=False)


def diagnostics(result):
    rows = [dict(code=code, severity='error', message=p['id']+': '+code) for p in result['quality']['parts'] for code in p['reasons']]
    if result['quality']['assembly']['crossing_pairs']:
        rows.append(dict(code='BASE_ASSEMBLY_OVERLAP', severity='error', message='The native head assembly crosses itself.'))
    return rows


def load(service, params):
    result = service.store.get('smooth_base_previews', key(service, params['preview_id']))
    require(result is not None, 'BASE_PREVIEW_NOT_FOUND')
    require(result['quality']['ready'], 'BASE_PREVIEW_UNRESOLVED'); return result


def publish(service, request):
    params = request['params']; result = load(service, params)
    saved = service.store.get('smooth_base_receipts', key(service, result['id']))
    if saved:
        service.scene.verify_smooth_base(saved)
        return dict(published=True, replayed=True, native_ids=saved['native_ids'], plan_id=result['id'], geometry_revalidated=False)
    source(service, result['definition'])
    require(result['support_digest'] == digest(service.inventory['geometry']), 'STALE_BASE_SUPPORTS')
    service.check(params); require(result['scene_revision'] == service.inventory['revision'], 'STALE_SCENE_REVISION')
    with service.scene.publish_smooth_base(result) as receipt:
        service.store.put('smooth_base_receipts', key(service, result['id']), receipt)
    service.identities.remember_journal(service.store.directory)
    return dict(published=True, native_ids=receipt['native_ids'], plan_id=result['id'])


def operations():
    return {'anatomy.smooth_base_preview': preview, 'anatomy.smooth_base_publish': publish}
