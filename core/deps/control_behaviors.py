from collections import OrderedDict

import bpy

from .controls import ControlIntent
from ..utils import depsgraph_for_scene
from ..visualization.sync import register_sync
from ..visualization.fiber_sync import register_fiber_sync
from ..visualization.muscle_sync import register_muscle_sync
from ..visualization.blob_sync import register_blob_sync
from ..visualization.fiber_sync_runtime import apply_fiber_control_update
from ..visualization.muscle_sync import apply_muscle_control_update
from ..visualization.blob_sync_runtime import apply_blob_control_update


_CONTROL_HANDLERS = OrderedDict()


def _obj_in_scene(scene, name):
    if scene is None or not name:
        return None
    return scene.objects.get(str(name))


def _depsgraph(scene):
    return depsgraph_for_scene(scene)


def _impact(entity_type, entity_id):
    return {entity_type: {entity_id}} if entity_id else {}


def _shape_sync_parts(sync):
    if not hasattr(sync, "collection_name") or not hasattr(sync, "_shape_sync_extensions"):
        return None, None
    return bpy.data.collections.get(sync.collection_name), None


def _shape_extension_impacts(sync, root, scene, obj, binding, vis_col, depsgraph):
    changed = set()
    for ext in sync._shape_sync_extensions:
        consumed, did, sid = ext.handle_object_update(sync, root, scene, vis_col, obj, depsgraph, control_binding=binding)
        if consumed:
            changed |= {str(sid)} if did and sid else set()
            break
    return {"SCP": changed} if changed else {}


def _apply_scp_shape(root, scene, intent, obj):
    sync = register_sync()
    vis_col, depsgraph = _shape_sync_parts(sync)
    depsgraph = _depsgraph(scene)
    if obj is None or vis_col is None or depsgraph is None:
        return {}
    return _shape_extension_impacts(sync, root, scene, obj, intent.payload.get("binding"), vis_col, depsgraph)


def _apply_scp_control(root, scene, intent):
    if not isinstance(intent, ControlIntent):
        return {}
    sid = str(intent.payload.get("scp_id") or "")
    if str(intent.control_type or "") == "SCP_CONTROL_OBJECT":
        return _impact("SCP", sid)
    return _apply_scp_shape(root, scene, intent, _obj_in_scene(scene, intent.payload.get("object_name")))


def _apply_fiber_control(root, scene, intent):
    obj = _obj_in_scene(scene, intent.payload.get("object_name"))
    if obj is None:
        return {}
    changed = apply_fiber_control_update(register_fiber_sync(), root, scene, obj, _depsgraph(scene))
    return _impact("FIBER", changed)


def _apply_muscle_control(root, scene, intent):
    obj = _obj_in_scene(scene, intent.payload.get("object_name"))
    if obj is None:
        return {}
    return _impact("MUSCLE", apply_muscle_control_update(register_muscle_sync(), root, scene, obj))


def _apply_blob_control(root, scene, intent):
    obj = _obj_in_scene(scene, intent.payload.get("object_name"))
    if obj is None:
        return {}
    return _impact("BLOB", apply_blob_control_update(register_blob_sync(), root, scene, obj))


def _as_control_types(control_types):
    if isinstance(control_types, str):
        return (str(control_types or "").strip(),)
    return tuple(str(value or "").strip() for value in tuple(control_types or tuple()) if str(value or "").strip())


def _register_handler(control_type, handler, replace):
    if control_type in _CONTROL_HANDLERS and not replace:
        raise ValueError(f"control handler already registered: {control_type}")
    _CONTROL_HANDLERS[control_type] = handler


def register_control_handler(control_types, handler, replace=False):
    types = _as_control_types(control_types)
    if not types:
        raise ValueError("at least one control type is required")
    for control_type in types:
        _register_handler(control_type, handler, replace)


def _builtin_handlers():
    return (
        (("SCP_CONTROL_OBJECT", "SCP_CURVE_POINT", "SCP_PARALLELEPIPED_VERTEX"), _apply_scp_control),
        (("FIBER_ENDPOINT", "FIBER_TOUCH"), _apply_fiber_control),
        (("MUSCLE_INFLATION",), _apply_muscle_control),
        (("BLOB_CONTROL",), _apply_blob_control),
    )


def register_builtin_control_handlers():
    for control_types, handler in _builtin_handlers():
        register_control_handler(control_types, handler, replace=True)


def apply_control_intent(root, scene, intent):
    handler = _CONTROL_HANDLERS.get(str(getattr(intent, "control_type", "") or ""))
    return {} if handler is None else handler(root, scene, intent)


register_builtin_control_handlers()
