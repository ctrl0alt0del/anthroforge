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
        validation.require(isinstance(change, dict) and not set(change) - {'id', 'excluded', 'cover', 'region'}, 'RELATIONSHIP_CHANGE')
        identity = change.get('id'); validation.require(identity in value['records'] and identity not in seen, 'RELATIONSHIP_NOT_FOUND')
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
        if change['cover'] is None: intent.pop('cover', None); intent.pop('region', None)
        else:
            validation.require(change['cover'] in row['pair'], 'RELATIONSHIP_COVER'); intent['cover'] = change['cover']
    if 'region' in change:
        if change['region'] is None: intent.pop('region', None)
        else: intent['region'] = selected_region(row, change['region'], manifest, domains)


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
    return value
