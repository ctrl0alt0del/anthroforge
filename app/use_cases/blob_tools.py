from ..queries.root import root_for_context
from .results import failure, success


def select_blob_control(context, blob_id=""):
    root = root_for_context(context)
    vcp, blob, error = _resolved_blob(root, blob_id)
    if blob is None:
        return failure(error)
    ctrl = _resolved_ctrl(context, root, vcp, blob)
    return failure("Blob control point not found.") if ctrl is None else success(value=ctrl)


def _resolved_blob(root, blob_id):
    if root is None:
        return None, None, ""
    vcp = root.af_vcp_system
    target_id = str(blob_id or vcp.active_vcp_id or "")
    if not target_id:
        return vcp, None, "Blob not found."
    blob = next((item for item in vcp.blobs if item.id == target_id), None)
    return vcp, blob, "" if blob is not None else "Blob not found."


def _find_ctrl(scene, root_name, blob_id):
    vis_col = _blob_vis_collection()(scene)
    return _find_blob_control()(vis_col, root_name, blob_id)


def _find_proxy(scene, root_name, blob_id):
    vis_col = _blob_vis_collection()(scene)
    return _find_blob_proxy()(vis_col, root_name, blob_id)


def _resolved_ctrl(context, root, vcp, blob):
    _activate_vcp(vcp, "BLOB", blob.id)
    previous = _active_object(context)
    _sync_entity(root, context.scene, "BLOB", {blob.id})
    proxy = _find_proxy(context.scene, root.name, blob.id)
    if proxy is None:
        return None
    _set_active_object(context, proxy)
    _sync_entity(root, context.scene, "BLOB", {blob.id})
    ctrl = _find_ctrl(context.scene, root.name, blob.id)
    _set_active_object(context, previous if ctrl is None else ctrl)
    return None if ctrl is None else _select_only(context, ctrl)


def _select_only(context, obj):
    for item in tuple(getattr(context, "selected_objects", ())):
        item.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj


def _activate_vcp(vcp, kind, entity_id):
    vcp.active_vcp_type, vcp.active_vcp_id = str(kind or ""), str(entity_id or "")


def _active_object(context):
    objects = getattr(getattr(context, "view_layer", None), "objects", None)
    return None if objects is None else getattr(objects, "active", None)


def _set_active_object(context, obj):
    objects = getattr(getattr(context, "view_layer", None), "objects", None)
    if objects is not None:
        objects.active = obj


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


def _blob_vis_collection():
    try:
        from ...core.visualization.blob_sync_helpers import get_vis_collection
    except ImportError:
        from core.visualization.blob_sync_helpers import get_vis_collection
    return lambda scene: get_vis_collection(scene, "AF_VCP_VIS")


def _find_blob_control():
    try:
        from ...core.visualization.blob_sync_helpers import find_blob_control
    except ImportError:
        from core.visualization.blob_sync_helpers import find_blob_control
    return find_blob_control


def _find_blob_proxy():
    try:
        from ...core.visualization.blob_sync_helpers import find_blob_proxy
    except ImportError:
        from core.visualization.blob_sync_helpers import find_blob_proxy
    return find_blob_proxy
