"""Managed draft recovery; saving never applies a Free path edit."""
import json
import bpy
from bpy.app.handlers import persistent
from . import free_fiber_editor as editor

_BUSY = False
_ROOTS = {}


def remember(root):
    _ROOTS[int(root.session_uid)] = root


def rebuild_sessions():
    _ROOTS.clear()
    for obj in bpy.data.objects:
        if any(key.startswith(editor.PREFIX) for key in obj.keys()): remember(obj)


def session_roots():
    for token, root in tuple(_ROOTS.items()):
        try:
            if any(key.startswith(editor.PREFIX) for key in root.keys()): yield root
            else: _ROOTS.pop(token, None)
        except ReferenceError: _ROOTS.pop(token, None)


def sessions():
    for root in session_roots():
        for key in tuple(root.keys()):
            if key.startswith(editor.PREFIX):
                fiber = next((f for f in root.af_vcp_system.fibers if f.id == key[len(editor.PREFIX):]), None)
                yield root, key, fiber


@persistent
def save(_unused=None):
    for root, key, fiber in sessions():
        if fiber is None: continue
        session = editor.state(root, fiber)
        try:
            for obj in editor.objects(session): obj.update_from_editmode()
            session['draft'] = editor.draft(root, fiber, session)
        except (ValueError, RuntimeError) as error: session['recovery_error'] = str(error)
        editor.save_state(root, fiber, session)


@persistent
def reconcile(_unused=None):
    global _BUSY
    if _BUSY or not hasattr(bpy.data, 'objects'): return
    _BUSY = True
    try: _reconcile_sessions()
    finally: _BUSY = False


def _reconcile_sessions():
    rebuild_sessions()
    live = set()
    for root, key, fiber in list(sessions()):
        if fiber is None: root.pop(key, None); continue
        session = editor.state(root, fiber); live.add(session['id']); session['stale'] = True
        scene = next((s for s in bpy.data.scenes if root.name in s.objects), None)
        if scene is not None and not editor.objects(session): editor.restore_draft(root, scene, fiber, session)
        editor.save_state(root, fiber, session)
    for obj in list(bpy.data.objects):
        if obj.get('af_free_editor_session') and obj['af_free_editor_session'] not in live: editor._remove_object(obj)


@persistent
def changed(scene, depsgraph):
    global _BUSY
    if _BUSY: return
    _BUSY = True
    try: _changed(scene, depsgraph)
    finally: _BUSY = False


def _changed(scene, depsgraph):
    rows = list(sessions())
    if not rows: return
    changed_ids = {getattr(update.id, 'name', '') for update in depsgraph.updates}
    for root, key, fiber in rows:
        if fiber is None: _discard(root, key); continue
        session = editor.state(root, fiber)
        if not session['stale'] and _relevant(root, scene, fiber, changed_ids):
            if editor.fingerprint(root, scene, fiber, depsgraph) != session['fingerprint']:
                session['stale'] = True; editor.save_state(root, fiber, session)


def _relevant(root, scene, fiber, changed_ids):
    if root.name in changed_ids: return True
    return any(obj.name in changed_ids or (obj.data and obj.data.name in changed_ids)
               for obj in scene.objects if obj.get('af_root_name') == root.name and not obj.get('af_free_editor_session'))


def _discard(root, key):
    session = json.loads(root[key]); root.pop(key, None)
    for obj in editor.objects(session): editor._remove_object(obj)


def delete(root, fiber_ids):
    for key in tuple(root.keys()):
        if key.startswith(editor.PREFIX) and key[len(editor.PREFIX):] in fiber_ids: _discard(root, key)
    for obj in list(bpy.data.objects):
        if obj.get('af_root_name') == root.name and obj.get('af_fiber_id') in fiber_ids and obj.get('af_fiber_proxy'):
            editor._remove_object(obj)


def _handlers():
    return ((bpy.app.handlers.save_pre, save), (bpy.app.handlers.load_post, reconcile),
            (bpy.app.handlers.undo_post, reconcile), (bpy.app.handlers.redo_post, reconcile),
            (bpy.app.handlers.depsgraph_update_post, changed))


def register():
    from ..core.visualization.delete_reconcile import set_fiber_delete_callback
    from ..core.importing.free_fibers import set_transaction
    from .free_fiber_import import run_import
    set_transaction(run_import)
    set_fiber_delete_callback(delete)
    for rows, method in _handlers():
        if method not in rows: rows.append(method)
    if hasattr(bpy.data, 'objects'): reconcile()


def unregister():
    from ..core.visualization.delete_reconcile import set_fiber_delete_callback
    from ..core.importing.free_fibers import set_transaction
    set_transaction(None)
    set_fiber_delete_callback(None)
    if hasattr(bpy.data, 'objects'):
        save()
        for root, key, fiber in list(sessions()):
            for obj in editor.objects(json.loads(root[key])): editor._remove_object(obj)
    for rows, method in _handlers():
        if method in rows: rows.remove(method)
    _ROOTS.clear()
