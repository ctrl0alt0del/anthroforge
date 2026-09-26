"""Journaled skeleton-space transfer into separate anatomical review meshes."""
from time import perf_counter
from ...core.authoring.codec import digest
from ...core.authoring.errors import require
from ...core.authoring.transfer_meshes import build, fingerprint
from . import transfer_bindings as bindings
from . import shape_transfers
from .transfer_bands import validate_domains

OPERATIONS = ('anatomy.transfer_sources', 'anatomy.transfer_preview', 'anatomy.transfer_publish')


def key(service, identity):
    return [service.inventory['root_id'] or service.inventory['scene_id'], identity]


def capture(service, names):
    method = getattr(service.scene, 'transfer_sources', None)
    require(callable(method), 'UNSUPPORTED_CAPABILITY', 'Reference mesh capture is unavailable.')
    return method(names)


def sources(service, request):
    service.check(request['params'])
    rows = capture(service, bindings.names(request['params']))
    replay = receipt(service, request, fingerprint(rows))
    if replay is not None:
        return replay
    asset = service.store.asset(dict(version='transfer_sources.v1', meshes=rows), 'transfer_sources')
    result = dict(assets=[asset], transfer=dict(version='transfer_sources.v1', meshes=source_summary(rows)))
    remember(service, request, fingerprint(rows), result)
    return result


def source_summary(rows):
    return [dict(object=name, topology_digest=row['topology_digest'], geometry_digest=row['geometry_digest'],
                 vertex_count=len(row['geometry']['vertices']), triangle_count=len(row['geometry']['triangles']))
            for name, row in rows.items()]


def preview(service, request):
    started = perf_counter()
    params = request['params']; service.check(params)
    rows = capture(service, bindings.names(params))
    pairs, annotations = bindings.resolve(service, params, rows); validate_domains(service, params); shape_transfers.validate_constraints(service, params, rows)
    replay = receipt(service, request, fingerprint(rows))
    if replay is not None:
        return replay
    result = shape_transfers.apply(service, params, rows, build(rows, params['source_objects'], pairs, params['settings'], annotations))
    identity = digest([result['version'], params, fingerprint(rows)])
    record = preview_record(service, identity, params, rows, result)
    service.store.put('transfer_previews', key(service, identity), record)
    reply = preview_reply(service, record, started)
    remember(service, request, record['source_fingerprint'], reply)
    return reply


def preview_record(service, identity, params, rows, result):
    return dict(id=identity, scene_revision=service.inventory['revision'], definition=params,
                source_fingerprint=fingerprint(rows), result=result, source_summary=source_summary(rows))


def preview_reply(service, record, started):
    result = record['result']
    path = service.store.path('transfer_previews', key(service, record['id']))
    info = {k: v for k, v in result.items() if k not in ('field', 'meshes', 'diagnostics', 'status')}
    info.update(preview_id=record['id'], meshes=[dict(source_object=r['source_object'], quality=r['quality']) for r in result['meshes']])
    return dict(status=result['status'], diagnostics=result['diagnostics'], transfer=info,
                assets=[dict(kind='transfer_preview', path=str(path), id=record['id'])],
                cost=dict(transfer_ms=(perf_counter()-started)*1000))


def load_preview(service, params):
    service.check(params)
    record = service.store.get('transfer_previews', key(service, params['preview_id']))
    require(record is not None, 'TRANSFER_PREVIEW_NOT_FOUND')
    require(record['scene_revision'] == service.inventory['revision'], 'STALE_SCENE_REVISION')
    rows = capture(service, bindings.names(record['definition']))
    require(fingerprint(rows) == record['source_fingerprint'], 'STALE_TRANSFER_SOURCE')
    pairs, _annotations = bindings.resolve(service, record['definition'], rows)
    require(digest(pairs) == digest(record['result']['correspondences']), 'STALE_TRANSFER_TARGET')
    shape_transfers.verify(service, record)
    return record


def publish(service, request):
    record = load_preview(service, request['params'])
    replay = receipt(service, request, record['source_fingerprint'])
    method = getattr(service.scene, 'publish_transfer', None)
    require(callable(method), 'UNSUPPORTED_CAPABILITY', 'Reference review publication is unavailable.')
    with method(record) as published:
        result = dict(published=True, replayed=replay is not None, status=record['result']['status'], diagnostics=record['result']['diagnostics'],
                      transfer=dict(preview_id=record['id'], experimental=False, **published))
        remember(service, request, record['source_fingerprint'], result)
    service.identities.remember_journal(service.store.directory)
    return result


def receipt(service, request, source_fingerprint):
    saved = service.store.get('transfer_requests', key(service, request['request_id']))
    if saved is None:
        return None
    require(saved['digest'] == digest(request), 'REQUEST_ID_REUSED')
    require(saved['source_fingerprint'] == source_fingerprint, 'STALE_TRANSFER_SOURCE')
    return dict(saved['response'], replayed=True)


def remember(service, request, source_fingerprint, result):
    service.store.put('transfer_requests', key(service, request['request_id']),
                      dict(digest=digest(request), source_fingerprint=source_fingerprint, response=result))


def operations():
    from .corrections import operations as corrections
    return dict(zip(OPERATIONS, (sources, preview, publish)), **corrections())
