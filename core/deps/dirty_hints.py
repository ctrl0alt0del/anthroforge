from .adapters import get_registered_entity_types


def empty_dirty_hints():
    return {et: set() for et in get_registered_entity_types()}


def dirty_hints_for(entity_type, ids):
    dirty = empty_dirty_hints()
    et = str(entity_type or "").strip().upper()
    if et in dirty:
        dirty[et] = set(ids or set())
    return dirty

