import bpy

from ..queries.root import root_for_context
from ..queries.vcp import active_soft_tissue_from_context, soft_tissue_proxy_for_context
from .results import failure, success


def recompute_soft_tissue(context, rebind=False):
    tissue = active_soft_tissue_from_context(context)
    if tissue is None:
        return failure("Soft Tissue VCP not found.")
    _sync(context, tissue.id, bool(rebind))
    return success("Soft tissue rebound." if rebind else "Soft tissue recomputed.")


def select_soft_tissue_base(context):
    tissue = active_soft_tissue_from_context(context)
    if tissue is None or tissue.base_object_ref is None:
        return failure("Soft tissue base is missing.")
    for obj in context.selected_objects:
        obj.select_set(False)
    tissue.base_object_ref.select_set(True)
    context.view_layer.objects.active = tissue.base_object_ref
    return success()


def duplicate_soft_tissue_snapshot(context):
    tissue = active_soft_tissue_from_context(context)
    proxy = soft_tissue_proxy_for_context(context, tissue)
    if proxy is None:
        return failure("Soft tissue final proxy is missing.")
    copy = proxy.copy()
    copy.data = proxy.data.copy()
    copy.name = f"{tissue.name}_Final"
    _clear_tags(copy)
    context.collection.objects.link(copy)
    copy.lock_location = copy.lock_rotation = copy.lock_scale = (False, False, False)
    return success(f"Created {copy.name}.", value=copy)


def _clear_tags(obj):
    for key in tuple(obj.keys()):
        if str(key).startswith("af_"):
            del obj[key]


def _sync(context, tissue_id, rebind):
    from ...app.runtime_api import sync_scene
    from ...core.deps.dirty_hints import dirty_hints_for
    root = root_for_context(context)
    payload = {"soft_tissue_force": True}
    if rebind:
        payload["soft_tissue_recapture_ids"] = [str(tissue_id)]
    sync_scene(root, context.scene, dirty_hints_for("SOFT_TISSUE", {tissue_id}), source="operator",
               event_type="SOFT_TISSUE_UPDATE", payload=payload)
