import bpy

from ..core.utils import get_af_root
from ..core.visualization.sync_runner import sync_from_blob_ids


class AF_OT_SelectBlobControl(bpy.types.Operator):
    bl_idname = "af.select_blob_control"
    bl_label = "Select Blob Control Point"
    bl_options = {"REGISTER", "UNDO"}

    blob_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}

        vcp = root.af_vcp_system
        bid = self.blob_id or vcp.active_vcp_id
        b = next((x for x in vcp.blobs if x.id == bid), None)
        if b is None:
            self.report({"ERROR"}, "Blob not found.")
            return {"CANCELLED"}

        # Ensure control exists.
        sync_from_blob_ids(root=root, scene=context.scene, blob_ids={b.id})

        ctrl = None
        for obj in context.scene.objects:
            if (
                obj.get("af_blob_control_gizmo")
                and obj.get("af_root_name") == root.name
                and obj.get("af_blob_id") == b.id
            ):
                ctrl = obj
                break

        if ctrl is None:
            self.report({"ERROR"}, "Blob control point not found.")
            return {"CANCELLED"}

        for o in context.selected_objects:
            o.select_set(False)
        ctrl.select_set(True)
        context.view_layer.objects.active = ctrl

        vcp.active_vcp_type = "BLOB"
        vcp.active_vcp_id = b.id
        return {"FINISHED"}
