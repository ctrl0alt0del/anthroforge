"""Atomic legacy migration; experimental records require an explicit action."""
from copy import deepcopy
from contextlib import contextmanager
import json
from . import store
from .identity import KEY, NAMESPACE, namespace, pair_id

CONFIG = 'af_pair_detection_configuration'


@contextmanager
def rollback(root):
    saved = {k: root.get(k) for k in (KEY, NAMESPACE, CONFIG)}
    try: yield
    except BaseException:
        for key, value in saved.items(): store.restore(root, key, value)
        raise


def ensure(root):
    with rollback(root):
        document = upgrade(root, store.initialize(root)); raw = json.loads(root.get(CONFIG, '{}'))
        if 'exclusions' not in raw: return document
        value = with_exclusions(document, raw.pop('exclusions'))
        with store.transaction(root, value, document['revision']) as result:
            root[CONFIG] = json.dumps(raw, sort_keys=True)
            return result


def upgrade(root, document):
    if document['schema'] == 2: return document
    value = deepcopy(document); value['schema'] = 2
    for row in value['records'].values():
        if row['intent'].get('cover'): row['intent']['mode'] = 'requested'
    with store.transaction(root, value, document['revision']) as result: return result


def with_exclusions(document, pairs):
    value = deepcopy(document)
    for row in value['records'].values(): row['intent'].pop('excluded', None)
    for pair in pairs:
        identity = pair_id(value['namespace'], pair)
        row = value['records'].setdefault(identity, store.new_record(value['namespace'], pair, 'manual'))
        row['intent']['excluded'] = True; row['origin'] = 'manual'
    return value


def exclusions(document):
    return [row['pair'] for row in document['records'].values() if row['intent'].get('excluded') and not row.get('unresolved_import')]


def explicit_experiment(root):
    from .importing import remap
    document = store.decode(root['af_experiment_relationships_v1'])
    mapping = {tuple(k): tuple(k) for row in document['records'].values() for k in row['pair']}
    with rollback(root):
        current = ensure(root); imported = remap(document, current['namespace'], mapping); value = deepcopy(current)
        for identity, row in imported['records'].items():
            existing = value['records'].get(identity, {})
            if existing.get('intent') and existing['intent'] != row['intent']: raise ValueError('RELATIONSHIP_MIGRATION_INTENT_CONFLICT')
            value['records'][identity] = row
        with store.transaction(root, value, current['revision']) as result: return result
