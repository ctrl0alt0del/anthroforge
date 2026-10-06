"""Shared immutable row preparations; callers receive private mutable rows."""
import numpy as np
from .muscle_profile_cache import cached, content_key


def prepared_rows(kind, rows, metadata, factory):
    from . import free_surface as limits
    keys = tuple(content_key(np.asarray(row, dtype=float)) for row in rows)
    budget = limits.MAX_STATIONS, limits.MAX_VERTICES, limits.MAX_TRIANGLES
    key = ('surface-rows-1', kind, keys, metadata, budget)
    result = cached(key, lambda: np.asarray(factory(), dtype=float))
    return result.tolist()
