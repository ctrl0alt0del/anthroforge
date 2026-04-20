import bpy

from ..core.assets.scp_mesh_library import save_asset_from_object


class AF_OT_RegisterMeshSCPAsset(bpy.types.Operator):
    bl_idname = "af.register_mesh_scp_asset"
    bl_label = "Register Mesh As SCP Asset"
    bl_description = "Save selected mesh as global SCP asset (available across sessions/projects)"
    bl_options = {"REGISTER", "UNDO"}

    display_name: bpy.props.StringProperty(
        name="Asset Name",
        default="",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.data is not None

    def execute(self, context):
        scene = context.scene
        obj = scene.af_new_scp_source_mesh_obj or context.active_object
        if obj is None or obj.type != "MESH" or obj.data is None:
            self.report({"ERROR"}, "Select a mesh object first.")
            return {"CANCELLED"}

        name = (self.display_name or "").strip() or obj.name

        try:
            asset_id = save_asset_from_object(obj, display_name=name)
        except Exception as e:
            self.report({"ERROR"}, f"Failed to register asset: {e}")
            return {"CANCELLED"}

        if hasattr(scene, "af_scp_type"):
            scene.af_scp_type = "MESH_ASSET"
        if hasattr(scene, "af_new_scp_mesh_asset_id"):
            scene.af_new_scp_mesh_asset_id = asset_id

        self.report({"INFO"}, f"Registered SCP mesh asset: {name} ({asset_id})")
        return {"FINISHED"}


    def invoke(self, context, event):
        obj = context.active_object
        if obj is not None:
            self.display_name = obj.name
        return context.window_manager.invoke_props_dialog(self)
