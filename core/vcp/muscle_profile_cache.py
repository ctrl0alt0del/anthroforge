"""Bounded immutable, content-keyed profile preparation and frame cache."""
from collections import OrderedDict
from hashlib import sha256
import numpy as np

CACHE = OrderedDict()
MAX_ENTRIES, MAX_BYTES = 32, 64 * 1024 * 1024


def clear_profile_cache(*unused):
    CACHE.clear()


def content_key(array, *metadata):
    values = np.ascontiguousarray(array)
    return sha256(values.tobytes() + repr((values.shape, metadata)).encode()).hexdigest()


def cached(key, factory):
    if key in CACHE:
        CACHE.move_to_end(key)
        return CACHE[key][0]
    value = factory()
    size = _freeze(value)
    if size <= MAX_BYTES:
        CACHE[key] = (value, size)
    while len(CACHE) > MAX_ENTRIES or sum(item[1] for item in CACHE.values()) > MAX_BYTES:
        CACHE.popitem(last=False)
    return value


def _freeze(value):
    if isinstance(value, np.ndarray):
        value.flags.writeable = False
        return value.nbytes
    if isinstance(value, (list, tuple)):
        return sum(_freeze(item) for item in value)
    if hasattr(value, "__dataclass_fields__"):
        return sum(_freeze(getattr(value, key)) for key in value.__dataclass_fields__)
    return 0
