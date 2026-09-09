"""Authoring commands commit intent before fallible evaluation."""
from copy import deepcopy
from ...core.authoring.validation import document as validate_document
from ...core.authoring.patching import apply_patch
from ...core.authoring.errors import require
from ...core.authoring.references import affected
from . import queries


def initialize(service, request):
    service.check(request['params'])
    data = service.identities.initialize()
    service.inventory = data
    return dict(scene_revision=data['revision'], root_id=data['root_id'], initialized=True)


def draft(service, request):
    params = request['params']
    old = service.repository.get(params['document_id'])
    replay = service.repository.replay(old or {}, request)
    if replay:
        return receipt_response(service, old, replay)
    service.check(params, old)
    require(params['document_id'] == params['document']['document_id'], 'DOCUMENT_ID_MISMATCH')
    return commit(service, request, validate_document(params['document']), old)


def patch(service, request):
    params, old = request['params'], service.load(request['params'])
    replay = service.repository.replay(old, request)
    if replay:
        return receipt_response(service, old, replay)
    service.check(params, old)
    document = validate_document(apply_patch(old['document'], params['patch']))
    return commit(service, request, document, old, params['patch'])


def commit(service, request, document, old=None, patch_value=None, extra=None):
    params = request['params']
    metadata = retained(old)
    metadata.update(extra or {})
    record, receipt = service.repository.commit(params['document_id'], params['expected_draft_revision'], document, request, service.inventory['revision'], metadata)
    changed = [p['path'] for p in (patch_value or [])]
    result = dict(draft_revision=record['draft_revision'], normalized_patch=patch_value or [], affected=affected(document, changed), receipt=receipt)
    result.update(queries.evaluation(service, record))
    saved = dict(state=result['status'], results=result.get('evaluation', {}))
    record['receipts'][request['request_id']]['response'] = deepcopy(result)
    saved['receipts'] = record['receipts']
    service.repository.finish(params['document_id'], record['draft_revision'], saved)
    return result


def retained(old):
    return {k: deepcopy(old[k]) for k in ('published', 'provisional', 'adoptions', 'local_overrides', 'compiled') if old and k in old}


def receipt_response(service, record, receipt):
    if 'response' in receipt:
        return dict(receipt['response'], replayed=True)
    return dict(queries.evaluation(service, record), draft_revision=receipt['revision'], replayed=True, recovery='Reevaluated committed intent after missing completion receipt.')
