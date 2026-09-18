"""Revalidated, idempotent native base publication with durable receipts."""
from ...core.authoring.codec import digest
from ...core.authoring.errors import require
from .base_definitions import load_base
from .transfer_bindings import target_domain
from .transfers import key


def load_plan(service, params):
    result = service.store.get('native_base_plans', key(service, params['plan_id']))
    require(result is not None, 'BASE_PLAN_NOT_FOUND'); load_base(service, result['base_id'])
    require(result['status'] == 'ready', 'BASE_PLAN_UNRESOLVED')
    require(result['support_digest'] == digest(service.inventory['geometry']), 'STALE_BASE_SUPPORTS')
    domains = {}
    for part in result['parts']:
        for fiber in part['fibers']:
            for hit in fiber['points']:
                domain = target_domain(service, hit['binding_spec'], domains)
                require(domain['definition_digest'] == hit['region_definition_digest'], 'STALE_BASE_REGION')
    return result


def publish_base_fibers(service, request):
    params = request['params']; plan = load_plan(service, params)
    saved = service.store.get('native_base_receipts', key(service, plan['id']))
    if saved is not None:
        service.scene.verify_native_base(saved)
        return dict(published=True, replayed=True, native_ids=saved['native_ids'], plan_id=plan['id'])
    service.check(params)
    require(plan['scene_revision'] == service.inventory['revision'], 'STALE_SCENE_REVISION')
    with service.scene.publish_native_base(plan) as receipt:
        service.store.put('native_base_receipts', key(service, plan['id']), receipt)
    service.identities.remember_journal(service.store.directory)
    return dict(published=True, native_ids=receipt['native_ids'], plan_id=plan['id'])
