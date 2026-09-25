"""Preview and transactional publication of versioned reference corrections."""
from ...core.authoring.codec import digest
from ...core.authoring.errors import require
from . import collision_inputs as bindings
from .transfers import key, receipt, remember


def collisions(service, request):
    row, supports, support_hash = bindings.inputs(service, request['params'])
    fingerprint = digest([row['geometry_digest'], support_hash]); saved = receipt(service, request, fingerprint)
    if saved is not None:
        return saved
    report = service.scene.transfer_collisions(row, supports, request['params']['settings'])
    result = dict(transfer=report, assets=[service.store.asset(report, 'transfer_collisions')])
    remember(service, request, fingerprint, result)
    return result


def preview(service, request):
    params = request['params']; row, supports, support_hash = bindings.inputs(service, params)
    fingerprint = digest([row['geometry_digest'], support_hash]); saved = receipt(service, request, fingerprint)
    if saved is not None:
        return saved
    fixed = bindings.fixed_indices(params, len(row['geometry']['vertices'])); contacts = bindings.contact_constraints(params, row, supports)
    settings = dict(params['settings'], guard_instance_ids=params.get('guard_instance_ids', []))
    output = service.scene.correct_transfer(row, supports, settings, fixed, contacts)
    record = record_for(params, output, fingerprint, service.inventory['revision'])
    service.store.put('transfer_corrections', key(service, record['id']), record)
    result = dict(status=record['result']['status'], transfer=dict(preview_id=record['id'], **output['validation'], fitting=output['fitting']),
                  diagnostics=diagnostics(output), assets=[service.store.asset(record, 'transfer_correction')])
    remember(service, request, fingerprint, result)
    return result


def diagnostics(output):
    return [dict(code=reason, severity='error', message='Correction preview failed '+reason+'. Source geometry is unchanged.') for reason in output['validation']['reasons']]


def record_for(params, output, fingerprint, revision):
    identity = digest(['transfer_correction.v1', params, fingerprint]); output['source_object'] = 'Corrected_'+params['source_object']
    result = dict(version='transfer_correction.v1', method='constrained_local_rbf.v1', field=output['field'],
                  status='success' if output['validation']['ready'] else 'unresolved', meshes=[output], annotations=[],
                  validation=output['validation'], diagnostics=diagnostics(output))
    return dict(id=identity, definition=params, scene_revision=revision, source_fingerprint=fingerprint, result=result)


def load(service, params):
    service.check(params); record = service.store.get('transfer_corrections', key(service, params['preview_id']))
    require(record is not None, 'CORRECTION_PREVIEW_NOT_FOUND')
    row, _supports, support_hash = bindings.inputs(service, record['definition'])
    require(record['source_fingerprint'] == digest([row['geometry_digest'], support_hash]), 'STALE_CORRECTION_GEOMETRY')
    require(record['result']['validation']['ready'], 'CORRECTION_NOT_READY', 'Inspect preview diagnostics before publishing.')
    return record


def publish(service, request):
    record = load(service, request['params']); saved = receipt(service, request, record['source_fingerprint'])
    with service.scene.publish_transfer(record) as published:
        result = dict(published=True, replayed=saved is not None, transfer=dict(preview_id=record['id'], **published,
                      validation=record['result']['validation'], downstream_rebuild_required=['base', 'fibers', 'inflation']))
        remember(service, request, record['source_fingerprint'], result)
    service.identities.remember_journal(service.store.directory)
    return result


def operations():
    from .attachment_grafts import operations as attachments
    return {**attachments(), 'anatomy.transfer_collisions': collisions, 'anatomy.transfer_correct_preview': preview,
            'anatomy.transfer_correct_publish': publish}
