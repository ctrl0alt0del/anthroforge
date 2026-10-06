"""Revision-guarded pair configuration and explicit footprint assets."""
from time import perf_counter
from ...core.authoring.codec import digest
from ...core.authoring.errors import require, AuthoringError
from ...core.authoring.reports import response, entity
from .native_profiles import _journal_transaction

OPS = tuple('muscles.pairs_' + name for name in ('inspect', 'refresh', 'footprint', 'order_footprint', 'configure'))
OPS += tuple('muscles.stacking_' + name for name in ('inspect', 'preview', 'configure'))


def dispatch(service, request, started):
    if request['op'] == 'muscles.stacking_preview': return preview(service, request, started)
    key = [service.inventory['root_id'] or service.inventory['scene_id'], request['request_id']]
    previous = service.store.get('v04_requests', key)
    require(not previous or previous['digest'] == digest(request), 'REQUEST_ID_REUSED')
    try:
        if request['op'].endswith('_configure'): return configure(service, request, key, started)
        state = service.scene.pairs_refresh() if request['op'] == 'muscles.pairs_refresh' else service.scene.pairs_inspect()
        result = reply(service, request, state, started)
        attach_assets(service, request, result)
        service.store.put('v04_requests', key, dict(digest=digest(request), response=result))
        return result
    except ValueError as error: raise AuthoringError(str(error).split(':')[0], str(error)) from error


def attach_assets(service, request, result):
    op, params = request['op'], request['params']
    if op.endswith('_footprint'):
        action = service.scene.pairs_order_footprint if op.endswith('_order_footprint') else service.scene.pairs_footprint
        index = resolve_index(service, params)
        data = action(index, params['expected_result_revision'])
        result['assets'] = [service.store.asset(data, 'muscle_layer_order.v1' if op.endswith('_order_footprint') else 'muscle_pair_footprint.v1')]


def preview(service, request, started):
    try:
        data = service.scene.stacking_preview(request['params'].get('configuration', {}))
        result = reply(service, request, service.scene.pairs_inspect(), started)
        result['entities'].append(entity(service.inventory['root_id'] or service.inventory['scene_id'], 'muscle_stacking_preview', preview=data))
        return result
    except ValueError as error: raise AuthoringError(str(error).split(':')[0], str(error)) from error


def configure(service, request, key, started):
    state = service.scene.pairs_inspect(); prior = service.scene.pairs_receipt(request['request_id'])
    if prior:
        require(prior['digest'] == digest(request), 'REQUEST_ID_REUSED')
        require(prior['configuration_revision'] == state['configuration_revision'], 'STALE_PAIR_RECEIPT')
        return dict(reply(service, request, state, started), replayed=True)
    service.check(request['params'])
    require(state['configuration_revision'] == request['params']['expected_configuration_revision'], 'STALE_CONFIGURATION_REVISION')
    with _journal_transaction(service.store, key):
        with service.scene.pairs_mutation(request['params']['configuration'], request['params']):
            return publish_configuration(service, request, key, started)


def publish_configuration(service, request, key, started):
    state = service.scene.pairs_inspect()
    receipt = dict(kind='muscle_pair_configuration.v1', digest=digest(request), configuration_revision=state['configuration_revision'])
    service.scene.pairs_receipt(request['request_id'], receipt)
    service.identities.remember_journal(service.store.directory)
    result = dict(reply(service, request, state, started), published=True)
    service.store.put('v04_requests', key, dict(digest=digest(request), response=result))
    return result


def reply(service, request, state, started):
    result = response(request, service.scene.capture_authoring()['revision'])
    result['entities'] = [entity(service.inventory['root_id'] or service.inventory['scene_id'], 'muscle_pair_detection', detection=state)]
    result['cost']['total_ms'] = (perf_counter()-started)*1000
    return result


def resolve_index(service, params):
    if 'relationship_id' not in params:
        require('pair_index' in params, 'PAIR_TARGET_REQUIRED')
        return params['pair_index']
    state = service.scene.pairs_inspect()
    require(state['result_revision'] == params['expected_result_revision'], 'PAIR_STALE_RESULT')
    row = next((p for p in state['pairs'] if p['relationship_id'] == params['relationship_id']), None)
    require(row is not None, 'RELATIONSHIP_NOT_FOUND')
    require('pair_index' not in params or params['pair_index'] == row['index'], 'RELATIONSHIP_PAIR_MISMATCH')
    return row['index']
