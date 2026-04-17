import bpy

from .controls import ControlIntent
from ..visualization.sync import register_sync
from ..visualization.fiber_sync import register_fiber_sync
from ..visualization.muscle_sync import register_muscle_sync
from ..visualization.blob_sync import register_blob_sync
from ..visualization.fiber_sync_runtime import apply_fiber_control_update
from ..visualization.muscle_sync import apply_muscle_control_update
from ..visualization.blob_sync_runtime import apply_blob_control_update


def _obj_in_scene(scene, name):
    if scene is None or not name:
        return None
    return scene.objects.get(str(name))


def _apply_scp_control(root, scene, intent):
    if not isinstance(intent, ControlIntent):
        return {}
    obj = _obj_in_scene(scene, intent.payload.get("object_name"))
    if obj is None:
        return {}
    sync = register_sync()
    if not hasattr(sync, "collection_name") or not hasattr(sync, "_shape_sync_extensions"):
        return {}
    vis_col = bpy.data.collections.get(sync.collection_name)
    if vis_col is None:
        return {}
    depsgraph = bpy.context.evaluated_depsgraph_get()
    control_binding = intent.payload.get("binding")
    changed_ids = set()
    for ext in sync._shape_sync_extensions:
        consumed, did, sid = ext.handle_object_update(
            sync, root, scene, vis_col, obj, depsgraph, control_binding=control_binding
        )
        if not consumed:
            continue
        if did and sid:
            changed_ids.add(str(sid))
        break
    return {"SCP": changed_ids} if changed_ids else {}


def _apply_fiber_control(root, scene, intent):
    obj = _obj_in_scene(scene, intent.payload.get("object_name"))
    if obj is None:
        return {}
    sync = register_fiber_sync()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    changed = apply_fiber_control_update(sync, root, scene, obj, depsgraph)
    return {"FIBER": {changed}} if changed else {}


def _apply_muscle_control(root, scene, intent):
    obj = _obj_in_scene(scene, intent.payload.get("object_name"))
    if obj is None:
        return {}
    sync = register_muscle_sync()
    changed = apply_muscle_control_update(sync, root, scene, obj)
    return {"MUSCLE": {changed}} if changed else {}


def _apply_blob_control(root, scene, intent):
    obj = _obj_in_scene(scene, intent.payload.get("object_name"))
    if obj is None:
        return {}
    sync = register_blob_sync()
    changed = apply_blob_control_update(sync, root, scene, obj)
    return {"BLOB": {changed}} if changed else {}


def apply_control_intent(root, scene, intent):
    ctype = str(getattr(intent, "control_type", "") or "")
    if ctype in ("SCP_CURVE_POINT", "SCP_PARALLELEPIPED_VERTEX"):
        return _apply_scp_control(root, scene, intent)
    if ctype in ("FIBER_ENDPOINT", "FIBER_TOUCH"):
        return _apply_fiber_control(root, scene, intent)
    if ctype == "MUSCLE_INFLATION":
        return _apply_muscle_control(root, scene, intent)
    if ctype == "BLOB_CONTROL":
        return _apply_blob_control(root, scene, intent)
    return {}
