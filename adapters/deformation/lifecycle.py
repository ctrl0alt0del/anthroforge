"""Invalidate work across file/undo boundaries and observe native contributor geometry."""
import bpy
from bpy.app.handlers import persistent
from ...core.warnings import session


@persistent
def reset(_):
    from . import runtime
    runtime.QUEUE.reset(); runtime.jobs.shutdown()
    runtime.SEEN.clear(); runtime.OWNERS.clear(); runtime.RUNNING.clear(); runtime.MODES.clear()


@persistent
def changed(scene, graph):
    roots = set()
    for update in graph.updates:
        obj = update.id
        if not isinstance(obj,bpy.types.Object): continue
        if not (update.is_updated_geometry or update.is_updated_transform): continue
        if not any(obj.get(k) for k in ("af_scp_geometry","af_muscle_proxy","af_fiber_proxy","af_soft_tissue_proxy","af_blob_proxy")): continue
        name = obj.get("af_root_name",""); root = scene.objects.get(name)
        if root is not None and root.get("af_deformation_reference") is not None: roots.add(session.id_token(root))
    for key in roots: session.CHANGES[key] = session.CHANGES.get(key,0)+1


def pairs():
    return ((bpy.app.handlers.load_pre,reset),(bpy.app.handlers.undo_pre,reset),
            (bpy.app.handlers.redo_pre,reset),(bpy.app.handlers.depsgraph_update_post,changed))


def register():
    for handlers, callback in pairs():
        if callback not in handlers: handlers.append(callback)


def unregister():
    for handlers, callback in pairs():
        if callback in handlers: handlers.remove(callback)
