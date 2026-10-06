"""Explicit ID remapping, with missing endpoints quarantined from live IDs."""
from copy import deepcopy
from uuid import uuid5, UUID
from .identity import pair_id, token
from . import store


def mapped_key(key, mapping, source_namespace):
    value = mapping.get(tuple(key))
    if value is not None: return list(value)
    return ['missing:' + str(uuid5(UUID(source_namespace), token(key))), key[1], key[2]]


def remap_record(row, new_namespace, mapping, source_namespace):
    value = deepcopy(row); translate = lambda k: mapped_key(k, mapping, source_namespace)
    value['pair'] = sorted(translate(k) for k in row['pair']); value['id'] = pair_id(new_namespace, value['pair'])
    value.update(state='requires_rescan', status='not_detected', origin='imported')
    for name in ('underlying', 'covering'):
        if value.get(name): value[name] = translate(value[name])
    intent = value['intent']
    if intent.get('cover'): intent['cover'] = translate(intent['cover'])
    if intent.get('region'): intent['region']['domain'] = translate(intent['region']['domain'])
    if any(tuple(k) not in mapping for k in row['pair']): value['unresolved_import'] = dict(namespace=source_namespace, pair=row['pair'])
    value.pop('evidence_signature', None); value.pop('policy', None)
    return value


def remap(document, new_namespace, mapping):
    store.validation.document(document)
    if len(set(mapping.values())) != len(mapping): raise ValueError('RELATIONSHIP_IMPORT_IDENTITY')
    result = store.empty(new_namespace)
    for row in document['records'].values():
        value = remap_record(row, new_namespace, mapping, document['namespace']); result['records'][value['id']] = value
    return result


def export(root):
    document = store.read(root)
    if document is None: return None
    value = deepcopy(document); value['manifest'] = {}
    for row in value['records'].values(): row.pop('evidence_signature', None); row['state'] = 'requires_rescan'
    return value


def merge(state):
    from .migration import ensure
    source = getattr(state.snapshot, 'relationships', None)
    if not source: return
    document = ensure(state.root); mapping = {tuple(k): (state.muscles[k[0]], k[1], k[2])
        for row in source['records'].values() for k in row['pair'] if k[0] in state.muscles}
    imported = remap(source, document['namespace'], mapping); value = deepcopy(document)
    if set(value['records']) & set(imported['records']): raise ValueError('RELATIONSHIP_IMPORT_COLLISION')
    value['records'].update(imported['records'])
    with store.transaction(state.root, value, document['revision']): pass
