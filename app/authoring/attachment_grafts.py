"""Versioned preview/publication for continuous reference attachment construction."""
from ...core.authoring.codec import digest
from ...core.authoring.errors import require
from . import collision_inputs
from .transfers import key, receipt, remember


def preview(service, request):
    params = request['params']; source, supports, support_hash = collision_inputs.inputs(service, params)
    fingerprint = digest([source['geometry_digest'], support_hash]); saved = receipt(service, request, fingerprint)
    if saved is not None:
        return saved
    output = service.scene.attachment_transfer(source, supports, params); identity = digest(['continuous_attachment.v1', params, fingerprint])
    record = record_for(identity, params, output, fingerprint, service.inventory['revision'])
    service.store.put('attachment_previews', key(service, identity), record)
    result = dict(status=record['result']['status'], transfer=dict(preview_id=identity, **output['validation']), assets=[service.store.asset(record, 'attachment_preview')])
    remember(service, request, fingerprint, result)
    return result


def record_for(identity, params, output, fingerprint, revision):
    output['source_object'] = 'Attached_'+params['source_object']
    result = dict(version='continuous_attachment.v1', method='bone_conforming_solid_graft.v1', field=None, meshes=[output], annotations=[],
                  status='success' if output['validation']['ready'] else 'unresolved', validation=output['validation'], diagnostics=[],
                  field_role='constructive_surface_replacement_no_deformation_field', annotation_mapping='must_rebind_after_remeshing')
    return dict(id=identity, definition=params, scene_revision=revision, source_fingerprint=fingerprint, result=result)


def load(service, params):
    service.check(params); record = service.store.get('attachment_previews', key(service, params['preview_id']))
    require(record is not None, 'ATTACHMENT_PREVIEW_NOT_FOUND')
    source, _supports, support_hash = collision_inputs.inputs(service, dict(record['definition'], expected_scene_revision=params['expected_scene_revision']))
    require(record['source_fingerprint'] == digest([source['geometry_digest'], support_hash]), 'STALE_ATTACHMENT_GEOMETRY')
    require(record['result']['validation']['ready'], 'ATTACHMENT_NOT_READY')
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
    return {'anatomy.transfer_attachment_preview': preview, 'anatomy.transfer_attachment_publish': publish}
