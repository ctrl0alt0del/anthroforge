import bpy
from ..visualization.blob_sync_helpers import get_vis_collection


def preserve_legacy_cache(state, snap, tissue):
    if tissue.evaluation_revision >= 1 or state.stage_root is None:
        return
    collection = get_vis_collection(state.scene, "AF_VCP_VIS")
    for obj in tuple(bpy.data.objects):
        if obj.get("af_import_stage_root") != state.stage_root.name or obj.get("af_soft_tissue_id") != snap.source_id:
            continue
        obj["af_root_name"], obj["af_soft_tissue_id"] = state.root.name, tissue.id
        del obj["af_import_stage_root"]
        if obj.name not in collection.objects:
            collection.objects.link(obj)
        state.kept_objects.append(obj)
