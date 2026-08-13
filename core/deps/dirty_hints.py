from .drivers import get_registered_entity_types


class DirtyHints(dict):
    def __init__(self, *args, full=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.full = bool(full)


def empty_dirty_hints():
    return DirtyHints({et: set() for et in get_registered_entity_types()}, full=True)


def dirty_hints_for(entity_type, ids):
    dirty = DirtyHints({et: set() for et in get_registered_entity_types()})
    et = str(entity_type or "").strip().upper()
    if et in dirty:
        dirty[et] = set(ids or set())
    return dirty
