"""Bounded rollback for Free-bearing package/SCP duplication destinations."""
import bpy
from .free_fiber_transaction import run
from .authoring.records import record, restore
from ..core.scp_runtime.prop_update_guard import suppress_scp_prop_updates


def run_import(root, scene, action):
    saved = _capture(root)
    try: return run(root, scene, action)
    except Exception:
        _restore(root, saved)
        raise


def _capture(root):
    return dict(scps={s.id for s in root.af_scp_system.scps},
                objects={o.name: (o, tuple(o.users_collection), dict(o.items())) for o in bpy.data.objects},
                shortcuts=[record(s) for s in root.af_shortcut_system.shortcuts],
                settings=[record(getattr(root, key)) for key in ('af_draft_skin_settings', 'af_topology_settings')])


def _restore(root, saved):
    with suppress_scp_prop_updates():
        for index in reversed(range(len(root.af_scp_system.scps))):
            if root.af_scp_system.scps[index].id not in saved['scps']: root.af_scp_system.scps.remove(index)
        root.af_shortcut_system.shortcuts.clear()
        for row in saved['shortcuts']: restore(root.af_shortcut_system.shortcuts.add(), row)
        for key, row in zip(('af_draft_skin_settings', 'af_topology_settings'), saved['settings']): restore(getattr(root, key), row)
    for obj in list(bpy.data.objects):
        if obj.name not in saved['objects']: bpy.data.objects.remove(obj, do_unlink=True)
    for obj, collections, values in saved['objects'].values(): _restore_object(obj, collections, values)


def _restore_object(obj, collections, values):
    for collection in tuple(obj.users_collection):
        if collection not in collections: collection.objects.unlink(obj)
    for collection in collections:
        if obj.name not in collection.objects: collection.objects.link(obj)
    for key in tuple(obj.keys()):
        if key not in values: del obj[key]
    for key, value in values.items(): obj[key] = value
