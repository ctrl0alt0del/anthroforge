try:
    from ...core.selection import get_active_af_entity
except ImportError:
    from core.selection import get_active_af_entity

from .root import root_for_context, scene_from_context


def active_entity(context):
    root = root_for_context(context)
    return ("NONE", "") if root is None else get_active_af_entity(root, context)


def has_active_entity(context, kind):
    return active_entity(context)[0] == str(kind or "").upper()


def _active_vcp_item(context, attr_name):
    root = root_for_context(context)
    if root is None:
        return None
    vcp = root.af_vcp_system
    return next((item for item in getattr(vcp, attr_name) if item.id == vcp.active_vcp_id), None)


def active_fiber_from_context(context):
    root = root_for_context(context)
    if root is None: return None
    kind, identity = get_active_af_entity(root, context)
    return next((item for item in root.af_vcp_system.fibers if item.id == identity), None) if kind == "FIBER" else None


def active_muscle_from_context(context):
    return _active_vcp_item(context, "muscles")


def active_fiber_surface_from_context(context):
    return _active_vcp_item(context, "fiber_surfaces")


def active_blob_from_context(context):
    return _active_vcp_item(context, "blobs")


def active_soft_tissue_from_context(context):
    return _active_vcp_item(context, "soft_tissues")


def blob_proxy(scene, root_name, blob_id):
    for obj in scene.objects:
        if obj.get("af_blob_proxy") and not obj.get("af_blob_mirror_proxy") and obj.get("af_root_name") == root_name and obj.get("af_blob_id") == blob_id:
            return obj
    return None


def blob_proxy_for_context(context, blob):
    root = root_for_context(context)
    scene = scene_from_context(context)
    if root is None or scene is None or blob is None:
        return None
    return blob_proxy(scene, root.name, blob.id)


def soft_tissue_proxy(scene, root_name, tissue_id):
    return next((obj for obj in scene.objects if obj.get("af_soft_tissue_proxy")
                 and not obj.get("af_soft_tissue_mirror_proxy") and obj.get("af_root_name") == root_name
                 and obj.get("af_soft_tissue_id") == tissue_id), None)


def soft_tissue_proxy_for_context(context, tissue):
    root = root_for_context(context)
    scene = scene_from_context(context)
    if root is None or scene is None or tissue is None:
        return None
    return soft_tissue_proxy(scene, root.name, tissue.id)
