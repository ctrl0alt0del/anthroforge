from ..queries.root import root_for_context
from .results import failure, success

try:
    from ...core.id_utils import next_prefixed_id
except ImportError:
    from core.id_utils import next_prefixed_id


def create_blob_vcp(context):
    root = root_for_context(context)
    if root is None:
        return failure("No AF_ROOT found.")
    blob = _new_blob(root.af_vcp_system.blobs, context.scene)
    target = getattr(context.scene, "af_new_blob_target_obj", None) or getattr(context, "active_object", None)
    _set_blob_target(blob, target)
    _activate(root.af_vcp_system, "BLOB", blob.id)
    _sync_entity(root, context.scene, "BLOB", {blob.id})
    return success(f"Added {blob.id}", value=blob)


def _new_blob(blobs, scene):
    blob = blobs.add()
    blob.id = next_prefixed_id(blobs, "BLOB")
    blob.name = blob.id
    _apply_values(blob, _blob_defaults(scene))
    return blob


def _blob_defaults(scene):
    return {
        "center_world": scene.cursor.location,
        "radius": 0.2,
        "shape": "SPHERE",
        "axis_scale": (1.0, 1.0, 1.0),
        "resolution": 24,
        "control_point_world": scene.cursor.location,
        "gravity_dir": (0.0, 0.0, -1.0),
        "sag_strength": 0.35,
        "sag_limit": 0.35,
        "stiffness": 0.25,
        "iterations": 20,
    }


def _apply_values(item, values):
    for key, value in values.items():
        setattr(item, key, value)


def _set_blob_target(blob, target):
    if not target:
        blob.attach_target_type, blob.attach_target_id, blob.attach_target_object_name = "NONE", "", ""
        return
    if target.get("af_muscle_proxy") and target.get("af_muscle_id"):
        blob.attach_target_type, blob.attach_target_id, blob.attach_target_object_name = "MUSCLE", target.get("af_muscle_id"), ""
        return
    if target.get("af_scp_geometry") and not target.get("af_scp_mirror") and target.get("af_scp_id"):
        blob.attach_target_type, blob.attach_target_id, blob.attach_target_object_name = "SCP", target.get("af_scp_id"), ""
        return
    blob.attach_target_type, blob.attach_target_id, blob.attach_target_object_name = "OBJECT", "", target.name


def _activate(vcp, kind, entity_id):
    vcp.active_vcp_type, vcp.active_vcp_id = str(kind or ""), str(entity_id or "")


def _sync_entity(root, scene, kind, entity_ids):
    hints = _dirty_hints_for()(kind, entity_ids)
    _sync_scene()(root=root, scene=scene, dirty_hints=hints)


def _sync_scene():
    try:
        from ...app.runtime_api import sync_scene
    except ImportError:
        from app.runtime_api import sync_scene
    return sync_scene


def _dirty_hints_for():
    try:
        from ...core.deps.dirty_hints import dirty_hints_for
    except ImportError:
        from core.deps.dirty_hints import dirty_hints_for
    return dirty_hints_for
