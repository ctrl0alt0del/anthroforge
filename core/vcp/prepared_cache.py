"""Memory-accounted LRU storage for immutable numerical preparations."""
from collections import OrderedDict, Counter
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from sys import getsizeof
import numpy as np


def immutable_size(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen: return 0
    seen.add(id(value))
    if isinstance(value, np.ndarray):
        value.flags.writeable = False
        return value.nbytes + 128
    if isinstance(value, dict): children = tuple(value.keys()) + tuple(value.values())
    elif isinstance(value, (tuple, list)): children = value
    elif is_dataclass(value): children = tuple(getattr(value, field.name) for field in fields(value))
    else: children = ()
    return getsizeof(value) + sum(immutable_size(child, seen) for child in children)


class PreparedCache(Mapping):
    def __init__(self):
        self._entries = OrderedDict()
        self.bytes = 0
        self.metrics = Counter()

    def __len__(self):
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)

    def __contains__(self, key):
        return key in self._entries

    def __getitem__(self, key):
        return self._entries[key]

    def clear(self):
        self._entries.clear()
        self.bytes = 0
        self.metrics.clear()

    def popitem(self, last=True):
        key, row = self._entries.popitem(last=last)
        self.bytes -= row[1]
        return key, row

    def get_or_create(self, key, factory, budget, entries=None):
        if key in self:
            self.metrics['hits'] += 1
            self._entries.move_to_end(key)
            return self[key][0]
        self.metrics['misses'] += 1
        value = factory()
        size = immutable_size(value) + immutable_size(key) + 128
        if size <= budget and entries != 0: self._store(key, value, size, budget, entries)
        else: self.metrics['oversized'] += 1
        return value

    def _store(self, key, value, size, budget, entries):
        self._entries[key] = value, size
        self.bytes += size
        while self.bytes > budget or (entries is not None and len(self) > entries):
            self.popitem(last=False)
            self.metrics['evictions'] += 1

    def stats(self):
        return dict(entries=len(self), bytes=self.bytes, **self.metrics)
