import bpy

from ..core.utils import get_af_root
from ..core.visualization.sync import register_sync
from ..core.visualization.fiber_sync import register_fiber_sync


class AF_OT_DeleteSelectedAFNode(bpy.types.Operator):
    bl_idname = "af.delete_selected_af_node"
    bl_label = "Delete Selected AF Node"
    bl_options = {"REGISTER", "UNDO"}

    target_type: bpy.props.EnumProperty(
        items=(
            ("AUTO", "Auto", ""),
            ("SCP", "SCP", ""),
            ("FIBER", "Fiber", ""),
        ),
        default="AUTO",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    target_id: bpy.props.StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"},)

    def _delete_scp(self, context, root, scp_id):
        scps = root.af_scp_system.scps

        idx = -1
        for i, scp in enumerate(scps):
            if scp.id == scp_id:
                idx = i
                break
        if idx < 0:
            self.report({"ERROR"}, f"SCP '{scp_id}' not found.")
            return {"CANCELLED"}

        child_scps = [scp.id for scp in scps if scp.parent_id == scp_id]
        child_fibers = []
        if hasattr(root, "af_vcp_system"):
            for fiber in root.af_vcp_system.fibers:
                if fiber.a_parent_id == scp_id or fiber.b_parent_id == scp_id:
                    child_fibers.append(fiber.id)

        if child_scps or child_fibers:
            parts = []
            if child_scps:
                parts.append(f"SCP children: {', '.join(child_scps[:5])}")
            if child_fibers:
                parts.append(f"Fiber children: {', '.join(child_fibers[:5])}")
            self.report({"ERROR"}, "Cannot delete SCP with children. " + " | ".join(parts))
            return {"CANCELLED"}

        scps.remove(idx)

        if len(scps) == 0:
            root.af_scp_system.active_scp_index = -1
        else:
            root.af_scp_system.active_scp_index = min(idx, len(scps) - 1)

        register_sync().sync_root_to_scene(root=root, scene=context.scene)
        register_fiber_sync().sync_root_to_scene(root=root, scene=context.scene)
        self.report({"INFO"}, f"Deleted SCP '{scp_id}'")
        return {"FINISHED"}

    def _delete_fiber(self, context, root, fiber_id):
        fibers = root.af_vcp_system.fibers

        idx = -1
        for i, f in enumerate(fibers):
            if f.id == fiber_id:
                idx = i
                break
        if idx < 0:
            self.report({"ERROR"}, f"Fiber '{fiber_id}' not found.")
            return {"CANCELLED"}

        fibers.remove(idx)

        if root.af_vcp_system.active_vcp_type == "FIBER" and root.af_vcp_system.active_vcp_id == fiber_id:
            root.af_vcp_system.active_vcp_type = "NONE"
            root.af_vcp_system.active_vcp_id = ""

        register_fiber_sync().sync_root_to_scene(root=root, scene=context.scene)
        self.report({"INFO"}, f"Deleted Fiber '{fiber_id}'")
        return {"FINISHED"}

    def execute(self, context):
        root = get_af_root(context.scene)
        if not self.target_id:
          self.target_type = "AUTO"
        if root is None:
            return bpy.ops.object.delete("INVOKE_DEFAULT")
        # explicit request from UI button
        if self.target_type == "SCP" and self.target_id:
            return self._delete_scp(context, root, self.target_id)
        if self.target_type == "FIBER" and self.target_id:
            return self._delete_fiber(context, root, self.target_id)

        # AUTO: from active object
        obj = context.active_object
        if obj is None:
            return bpy.ops.object.delete("INVOKE_DEFAULT")

        if obj.get("af_proxy") and obj.get("af_root_name") == root.name and obj.get("af_scp_id"):
            return self._delete_scp(context, root, obj.get("af_scp_id"))

        if obj.get("af_fiber_proxy") and obj.get("af_root_name") == root.name and obj.get("af_fiber_id"):
            return self._delete_fiber(context, root, obj.get("af_fiber_id"))

        return bpy.ops.object.delete("INVOKE_DEFAULT")
