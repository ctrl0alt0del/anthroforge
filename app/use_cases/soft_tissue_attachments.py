from ..queries.root import root_for_context
from ..queries.vcp import active_soft_tissue_from_context
from .results import failure, success
from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates

_MASK_ITEMS = []


def edit_attachment(context, index=None):
    tissue = active_soft_tissue_from_context(context)
    if tissue is None:
        return failure("Soft Tissue VCP not found.")
    if index is not None and not 0 <= index < len(tissue.attachments):
        return failure("Attachment row no longer exists.")
    with suppress_vcp_prop_updates():
        if index is None:
            row = tissue.attachments.add()
            row.mode, row.mask_attribute = "SOFT", "ALL"
        else:
            tissue.attachments.remove(index)
    _sync_regions(context, tissue)
    return success("Attachment added." if index is None else "Attachment removed.")


def _sync_regions(context, tissue):
    from ..runtime_api import sync_scene
    from ...core.deps.dirty_hints import dirty_hints_for
    payload = {"soft_tissue_region_recapture_ids": [str(tissue.id)]}
    sync_scene(root_for_context(context), context.scene, dirty_hints_for("SOFT_TISSUE", {tissue.id}),
               source="operator", event_type="SOFT_TISSUE_UPDATE", payload=payload)


def mask_choices(_operator, context):
    global _MASK_ITEMS
    tissue = active_soft_tissue_from_context(context)
    domain = "POINT" if tissue is None else tissue.base_domain
    names = ["ALL"] + {"POINT": [], "CURVE": ["BACKING", "ENDPOINTS"],
                       "SURFACE": ["BACKING", "BOUNDARY", "SUSPENSION"]}[domain]
    base = None if tissue is None else tissue.base_object_ref
    if base is not None and base.type == "MESH":
        names += [group.name for group in base.vertex_groups if group.name.upper() not in names]
    _MASK_ITEMS = [(name, name, "Attachment region") for name in names]
    return _MASK_ITEMS


def select_mask(context, index, mask):
    tissue = active_soft_tissue_from_context(context)
    if tissue is None or not 0 <= index < len(tissue.attachments):
        return failure("Attachment row no longer exists.")
    tissue.attachments[index].mask_attribute = mask
    return success()
