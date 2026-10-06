"""Blender identity lifecycle; new copies rekey, ambiguous loaded duplicates stop."""
from uuid import uuid4
import bpy
from bpy.app.handlers import persistent
from .identity import NAMESPACE, KEY, namespace
from . import store, migration

KNOWN = {}
IMPORTING = set()
LOADING = False
IMPORT_ACTIVE = False


def ensure_unique(root):
    value = namespace(root)
    matches = [o for o in bpy.data.objects if o.get('anthroforge_root') and o.get(NAMESPACE) == value]
    if len(matches) > 1: raise ValueError('RELATIONSHIP_IDENTITY_CONFLICT')


def rekey(root):
    from .importing import remap
    document = store.read(root)
    if document is None: return migration.ensure(root)
    mapping = {tuple(k): tuple(k) for row in document['records'].values() for k in row['pair']}
    with migration.rollback(root):
        root[NAMESPACE] = str(uuid4()); value = remap(document, root[NAMESPACE], mapping)
        root[KEY] = store.encode(dict(value, revision=document['revision'] + 1))
    return value


def reset():
    global LOADING
    KNOWN.clear()
    for obj in bpy.data.objects:
        if obj.get('anthroforge_root'): KNOWN[obj.session_uid] = obj.get(NAMESPACE)
    LOADING = False


def suspend():
    global LOADING, IMPORT_ACTIVE
    LOADING = True; IMPORT_ACTIVE = False; KNOWN.clear(); IMPORTING.clear()


def discover(root):
    if LOADING: return
    value = root.get(NAMESPACE)
    if root.session_uid not in KNOWN and value and value in KNOWN.values():
        try: rekey(root)
        except ValueError: pass  # Preserve damaged data; capture reports the identity/document failure.
    KNOWN[root.session_uid] = root.get(NAMESPACE)


@persistent
def import_before(_context):
    global IMPORT_ACTIVE
    if LOADING: return
    IMPORT_ACTIVE = True
    IMPORTING.clear(); IMPORTING.update(o.session_uid for o in bpy.data.objects)


@persistent
def import_after(_context):
    global IMPORT_ACTIVE
    if LOADING or not IMPORT_ACTIVE: return
    for obj in bpy.data.objects:
        if obj.session_uid not in IMPORTING and obj.get('anthroforge_root') and obj.get(NAMESPACE): rekey(obj)
    IMPORTING.clear()
    IMPORT_ACTIVE = False
