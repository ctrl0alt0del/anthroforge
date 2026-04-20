import bpy
from ..core.assets.scp_mesh_library import delete_asset


class AF_OT_SelectMeshSCPAsset(bpy.types.Operator):
    bl_idname = "af.select_mesh_scp_asset"
    bl_label = "Select Mesh SCP Asset"
    bl_options = {"INTERNAL"}

    asset_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        context.scene.af_new_scp_mesh_asset_id = self.asset_id
        return {"FINISHED"}


class AF_OT_DeleteMeshSCPAsset(bpy.types.Operator):
    bl_idname = "af.delete_mesh_scp_asset"
    bl_label = "Delete Mesh SCP Asset"
    bl_options = {"REGISTER", "UNDO"}

    asset_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        if not self.asset_id:
            self.report({"ERROR"}, "No asset selected.")
            return {"CANCELLED"}

        ok = delete_asset(self.asset_id)
        if not ok:
            self.report({"ERROR"}, f"Asset not found: {self.asset_id}")
            return {"CANCELLED"}

        if context.scene.af_new_scp_mesh_asset_id == self.asset_id:
            context.scene.af_new_scp_mesh_asset_id = ""

        self.report({"INFO"}, f"Deleted asset: {self.asset_id}")
        return {"FINISHED"}
