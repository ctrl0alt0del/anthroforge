"""Revision guarded root-owned document, without numerical or Blender dependencies."""
from contextlib import contextmanager
import json
from .identity import KEY, NAMESPACE, namespace, pair_id
from .fingerprints import digest
from . import validation


def empty(root_id):
    return dict(schema=2, namespace=root_id, revision=0, manifest={}, records={})


def encode(document):
    validation.document(document)
    return json.dumps(dict(document=document, checksum=digest(document)), sort_keys=True, allow_nan=False)


def decode(blob):
    validation.require(isinstance(blob, str) and len(blob) <= 64 * 1024 * 1024, 'RELATIONSHIP_RESOURCE_LIMIT')
    try:
        outer = json.loads(blob); value = validation.document(outer['document'])
        validation.require(digest(value) == outer['checksum'], 'RELATIONSHIP_CHECKSUM')
        return value
    except (KeyError, TypeError, json.JSONDecodeError) as error: raise ValueError('RELATIONSHIP_DOCUMENT') from error


def read(root):
    identity = namespace(root)
    if KEY not in root: return empty(identity) if identity else None
    value = decode(root[KEY])
    validation.require(value['namespace'] == identity, 'RELATIONSHIP_NAMESPACE')
    return value


def initialize(root):
    prior = root.get(NAMESPACE)
    try:
        namespace(root, create=True)
        return read(root)
    except BaseException:
        restore(root, NAMESPACE, prior)
        raise


def restore(root, key, value):
    if value is None:
        if key in root: del root[key]
    else: root[key] = value


@contextmanager
def transaction(root, document, expected):
    old = root.get(KEY); current = read(root)
    validation.require(current is not None and current['revision'] == expected, 'RELATIONSHIP_STALE_REVISION')
    validation.require(document['namespace'] == current['namespace'], 'RELATIONSHIP_NAMESPACE')
    value = dict(document, revision=expected + 1); blob = encode(value)
    try:
        root[KEY] = blob
        yield value
    except BaseException:
        restore(root, KEY, old)
        raise


def new_record(identity, pair, origin='automatic'):
    return dict(id=pair_id(identity, pair), pair=sorted([list(v) for v in pair]), origin=origin,
        intent={}, state='requires_rescan', status='not_detected', underlying=None, covering=None)
