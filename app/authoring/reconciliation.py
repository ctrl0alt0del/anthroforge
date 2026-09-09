"""Three-state comparison with explicit restoration or preserved overrides."""
from ...core.authoring.codec import digest
from ...core.authoring.errors import require
from . import construction


def reconcile(service, request):
    params, record = request['params'], service.load(request['params'])
    service.check(params, record)
    published = record.get('published')
    require(published, 'PUBLICATION_REQUIRED')
    change = service.native_edits.native_changes(published)
    if params['mode'] == 'inspect':
        return dict(comparison=change, authored_changed=record['compiled']['source_digest'] != digest(record['document']))
    if params['mode'] == 'adopt':
        return adopt(service, request, record, change)
    with service.native_edits.restoration(record['document']['document_id']):
        record['compiled']['scene_revision'] = service.inventory['revision']
        service.repository.finish(params['document_id'], record['draft_revision'], dict(compiled=record['compiled']))
        return construction.publish(service, request)


def adopt(service, request, record, change):
    from .drafts import commit
    from ...core.authoring.reconciliation import semantic_patch
    from ...core.authoring.patching import apply_patch
    from ...core.authoring.validation import document as validate_document
    patch, unresolved = semantic_patch(record['document'], record['published'], change)
    patch, unresolved = with_routes(service, record, change, patch, unresolved)
    overrides = record.get('local_overrides', [])
    if unresolved:
        overrides += [dict(native=change['current'], baseline=change['baseline'], subjects=unresolved, state='unresolved', reason='Native edit preserved; semantic inverse is ambiguous.')]
    authored = validate_document(apply_patch(record['document'], patch))
    result = commit(service, request, authored, record, patch, extra=dict(local_overrides=overrides))
    service.native_edits.authorize_restore(record['document']['document_id'])
    return result


def with_routes(service, record, change, operations, unresolved):
    from .route_reconciliation import patches
    routes, failures = patches(service, record, change)
    return operations+routes, unresolved+failures
