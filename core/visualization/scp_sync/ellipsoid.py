class EllipsoidSCPSyncExtension:
    shape_type = "ELLIPSOID"

    def sync_post(self, sync_manager, root, scene, vis_col):
        # No shape-specific helper sync for ellipsoid yet.
        return

    def handle_object_update(self, sync_manager, root, scene, vis_col, obj, depsgraph):
        # No shape-specific helper object handling yet.
        return False, False, None
