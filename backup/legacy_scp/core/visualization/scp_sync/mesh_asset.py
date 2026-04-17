class MeshAssetSCPSyncExtension:
    shape_type = "MESH_ASSET"

    def sync_post(self, sync_manager, root, scene, vis_col):
        # No shape-specific helper sync for mesh asset yet.
        return

    def handle_object_update(self, sync_manager, root, scene, vis_col, obj, depsgraph, control_binding=None):
        # No shape-specific helper object handling yet.
        return False, False, None
