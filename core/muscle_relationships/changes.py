"""Shared validation and pure intent mutations for UI, authoring and previews."""
from copy import deepcopy
from .identity import token
from . import validation


def configuration_intent(document):
    if document is None: return {}
    return {k: row['intent'] for k, row in sorted(document['records'].items()) if row['intent']}


def apply(document, changes, manifest, domains):
    value = deepcopy(document)
    validation.require(isinstance(changes, list), 'RELATIONSHIP_CHANGES')
    seen = set()
    for change in changes:
        validation.require(isinstance(change, dict) and not set(change) - {'id', 'pair', 'excluded', 'cover', 'region', 'mode'}, 'RELATIONSHIP_CHANGE')
        identity = resolve_change(value, change, manifest)
        validation.require(identity in value['records'] and identity not in seen, 'RELATIONSHIP_NOT_FOUND')
        seen.add(identity); update(value['records'][identity], change, manifest, domains)
    validation.document(value)
    return value


def update(row, change, manifest, domains):
    intent = row['intent']; row['origin'] = 'manual'
    if 'excluded' in change:
        validation.require(type(change['excluded']) is bool, 'RELATIONSHIP_EXCLUDED')
        if change['excluded']: intent['excluded'] = True
        else: intent.pop('excluded', None)
    if 'cover' in change:
        if change['cover'] != intent.get('cover'): intent.pop('region', None)
        if change['cover'] is None: intent.pop('cover', None); intent.pop('mode', None)
        else:
            validation.require(change['cover'] in row['pair'], 'RELATIONSHIP_COVER'); intent['cover'] = change['cover']
    if 'mode' in change: intent['mode'] = change['mode']
    if 'region' in change:
        if change['region'] is None: intent.pop('region', None)
        else: intent['region'] = selected_region(row, change['region'], manifest, domains)


def resolve_change(document, change, manifest):
    from .store import new_record
    from .identity import pair_id
    if 'pair' not in change: return change.get('id')
    pair = change['pair']
    validation.require(isinstance(pair, list) and len(pair) == 2 and pair[0] != pair[1], 'RELATIONSHIP_PAIR')
    for key in pair: validation.domain(key)
    validation.require(all(token(k) in manifest.get('domains', {}) for k in pair), 'RELATIONSHIP_MISSING_REFERENCE')
    identity = pair_id(document['namespace'], pair)
    validation.require(change.get('id', identity) == identity, 'RELATIONSHIP_ID')
    document['records'].setdefault(identity, new_record(document['namespace'], pair, 'manual'))
    return identity


def selected_region(row, faces, manifest, domains):
    cover = row['intent'].get('cover') or row.get('covering')
    validation.require(cover is not None, 'RELATIONSHIP_COVER_REQUIRED')
    available = {token((d.key.muscle, d.key.instance, d.key.side)): d for d in domains}
    validation.require(token(cover) in available, 'RELATIONSHIP_MISSING_REFERENCE')
    d = available[token(cover)]; stamp = manifest['domains'][token(cover)]
    value = dict(domain=cover, faces=faces, topology=stamp['topology'], version=manifest['version'])
    validation.region(value, row['pair'])
    validation.require(not set(map(tuple, faces)) - set(zip(d.parts.tolist(), d.sources.tolist())), 'RELATIONSHIP_UNKNOWN_FACE')
    value['faces'] = sorted([list(v) for v in set(map(tuple, faces))]); row['intent']['cover'] = cover
    if row['intent'].get('mode') == 'automatic': row['intent']['mode'] = 'requested'
    return value
