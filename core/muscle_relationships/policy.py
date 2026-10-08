"""Owned immutable policy records submitted with a numerical generation."""
from dataclasses import dataclass
from .fingerprints import key
from .reconcile import intent_status


@dataclass(frozen=True)
class RelationshipPolicy:
    pair: tuple
    cover: tuple = ()
    excluded: bool = False
    region: tuple = ()
    invalid: bool = False
    mode: str = 'requested'


def capture(document, manifest, domains):
    available = {key(d): d for d in domains}; result = []
    for row in document['records'].values():
        pair = tuple(tuple(k) for k in row['pair']); intent = row.get('intent', {})
        if row.get('unresolved_import') or not intent or any(k not in available for k in pair): continue
        cover = tuple(intent.get('cover') or ()); region = intent.get('region')
        faces = tuple(tuple(f) for f in region['faces']) if region else ()
        invalid = bool(intent_status(intent, manifest))
        if region: invalid |= bool(set(faces) - set(zip(available[cover].parts.tolist(), available[cover].sources.tolist())))
        result.append(RelationshipPolicy(pair, cover, bool(intent.get('excluded')), faces, invalid,
            intent.get('mode', 'requested' if cover else 'automatic')))
    return tuple(result)
