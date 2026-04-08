import bpy

from ..core.utils import get_af_root
from ..core.deps.dirty_hints import dirty_hints_for
from ..core.visualization.sync_runner import sync_from_dirty_hints


class AF_OT_SelectBlobControl(bpy.types.Operator):
    bl_idname = "af.select_blob_control"
    bl_label = "Select Blob Control Point"
    bl_options = {"REGISTER", "UNDO"}

    blob_id: bpy.props.StringProperty(default="")

    def _resolve_blob(self, root):
        vcp = root.af_vcp_system
        bid = self.blob_id or vcp.active_vcp_id
        return vcp, next((x for x in vcp.blobs if x.id == bid), None)

    def _find_control(self, context, root_name, blob_id):
        for obj in context.scene.objects:
            if obj.get("af_blob_control_gizmo") and obj.get("af_root_name") == root_name:
                if obj.get("af_blob_id") == blob_id:
                    return obj
        return None

    def _select_only(self, context, obj):
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}
        vcp, b = self._resolve_blob(root)
        if b is None:
            self.report({"ERROR"}, "Blob not found.")
            return {"CANCELLED"}
        sync_from_dirty_hints(
            root=root,
            scene=context.scene,
            dirty_hints=dirty_hints_for("BLOB", {b.id}),
        )
        ctrl = self._find_control(context, root.name, b.id)
        if ctrl is None:
            self.report({"ERROR"}, "Blob control point not found.")
            return {"CANCELLED"}
        self._select_only(context, ctrl)
        vcp.active_vcp_type = "BLOB"
        vcp.active_vcp_id = b.id
        return {"FINISHED"}
