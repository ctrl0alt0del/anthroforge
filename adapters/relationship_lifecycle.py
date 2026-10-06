"""Transient region-session and import lifecycle hooks."""
import bpy
from bpy.app.handlers import persistent
from . import relationship_region_editor as editor
from ..core.muscle_relationships import blender_identity


@persistent
def save_before(_unused):
    for draft in tuple(editor.SESSIONS.values()):
        try: draft.selected = editor.selection(draft)
        except (ValueError, ReferenceError): pass
        editor.remove_objects(draft); draft.suspended = True


@persistent
def save_after(_unused):
    for draft in tuple(editor.SESSIONS.values()):
        if draft.suspended:
            draft.suspended = False; editor.create(draft)


@persistent
def clear(_unused):
    editor.clear()


@persistent
def cleanup(scene, _depsgraph):
    live = {o.session_uid for o in bpy.data.objects if o.get('anthroforge_root')}
    for key, draft in tuple(editor.SESSIONS.items()):
        if key not in live: editor.remove_objects(draft); editor.SESSIONS.pop(key)


def handlers():
    return (('save_pre', save_before), ('save_post', save_after), ('save_post_fail', save_after),
        ('load_pre', clear), ('undo_pre', clear), ('redo_pre', clear), ('depsgraph_update_post', cleanup),
        ('blend_import_pre', blender_identity.import_before), ('blend_import_post', blender_identity.import_after))


def register():
    for name, action in handlers():
        rows = getattr(bpy.app.handlers, name, None)
        if rows is not None and action not in rows: rows.append(action)


def unregister():
    editor.clear()
    for name, action in handlers():
        rows = getattr(bpy.app.handlers, name, ())
        if action in rows: rows.remove(action)
