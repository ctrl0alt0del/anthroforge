"""Bounded immutable, content-keyed profile preparation and frame cache."""
from hashlib import sha256
import numpy as np
from .prepared_cache import PreparedCache, immutable_size

CACHE = PreparedCache()
MAX_ENTRIES, MAX_BYTES = None, 64 * 1024 * 1024


def clear_profile_cache(*unused):
    CACHE.clear()


def content_key(array, *metadata):
    values = np.ascontiguousarray(array)
    return sha256(values.tobytes() + repr((values.shape, metadata)).encode()).hexdigest()


def cached(key, factory):
    return CACHE.get_or_create(key, factory, MAX_BYTES, MAX_ENTRIES)


def _freeze(value):
    return immutable_size(value)
