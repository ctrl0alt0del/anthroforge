"""Persistent relationship identities; runtime handles never enter saved records."""
from uuid import UUID, uuid4, uuid5
import json

NAMESPACE = 'af_relationship_namespace'
KEY = 'af_muscle_relationships'


def token(value):
    return json.dumps(value, separators=(',', ':'), sort_keys=True, allow_nan=False)


def domain_key(value):
    return [value[k] for k in ('muscle', 'instance', 'side')]


def pair_id(namespace, pair):
    return str(uuid5(UUID(namespace), token(sorted(tuple(k) for k in pair))))


def namespace(root, create=False):
    value = root.get(NAMESPACE)
    if value is None and create: root[NAMESPACE] = value = str(uuid4())
    if value is None: return None
    try: return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as error: raise ValueError('RELATIONSHIP_NAMESPACE') from error
