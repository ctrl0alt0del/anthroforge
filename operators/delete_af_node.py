import bpy

from ..core.utils import get_af_root
from ..core.deps.dirty_hints import dirty_hints_for
from ..core.visualization.sync_runner import sync_from_dirty_hints


class AF_OT_DeleteSelectedAFNode(bpy.types.Operator):
    bl_idname = "af.delete_selected_af_node"
    bl_label = "Delete Selected AF Node"
    bl_options = {"REGISTER", "UNDO"}

    target_type: bpy.props.EnumProperty(
        items=(
            ("AUTO", "Auto", ""),
            ("SCP", "SCP", ""),
            ("FIBER", "Fiber", ""),
            ("BLOB", "Blob", ""),
        ),
        default="AUTO",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    target_id: bpy.props.StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    def _find_scp_index(self, scps, scp_id):
        for i, scp in enumerate(scps):
            if scp.id == scp_id:
                return i
        return -1

    def _find_scp_object(self, context, root_name, scp_id):
        for obj in context.scene.objects:
            if (
                obj.get("af_scp")
                and not obj.get("af_scp_mirror")
                and obj.get("af_root_name") == root_name
                and obj.get("af_scp_id") == scp_id
            ):
                return obj
        return None

    def _remove_scp_tags(self, obj):
        for key in ("af_scp", "af_root_name", "af_scp_id"):
            try:
                if key in obj:
                    del obj[key]
            except Exception:
                pass

    def _collect_scp_children(self, root, scps, scp_id):
        child_scps = [scp.id for scp in scps if scp.parent_id == scp_id]
        child_fibers = []
        if hasattr(root, "af_vcp_system"):
            for fiber in root.af_vcp_system.fibers:
                if fiber.a_parent_id == scp_id or fiber.b_parent_id == scp_id:
                    child_fibers.append(fiber.id)
        return child_scps, child_fibers

    def _set_active_scp_after_remove(self, root, scps, idx):
        root.af_scp_system.active_scp_index = -1 if len(scps) == 0 else min(idx, len(scps) - 1)

    def _delete_scp(self, context, root, scp_id):
        scps = root.af_scp_system.scps
        idx = self._find_scp_index(scps, scp_id)
        if idx < 0:
            self.report({"ERROR"}, f"SCP '{scp_id}' not found.")
            return {"CANCELLED"}
        child_scps, child_fibers = self._collect_scp_children(root, scps, scp_id)
        if child_scps or child_fibers:
            parts = []
            if child_scps:
                parts.append(f"SCP children: {', '.join(child_scps[:5])}")
            if child_fibers:
                parts.append(f"Fiber children: {', '.join(child_fibers[:5])}")
            self.report({"ERROR"}, "Cannot delete SCP with children. " + " | ".join(parts))
            return {"CANCELLED"}

        obj = self._find_scp_object(context, root.name, scp_id)
        if obj is not None:
            self._remove_scp_tags(obj)
            if getattr(context.scene, "af_scp_parent_obj", None) == obj:
                context.scene.af_scp_parent_obj = None

        scps.remove(idx)
        self._set_active_scp_after_remove(root, scps, idx)
        sync_from_dirty_hints(
            root=root,
            scene=context.scene,
            dirty_hints=dirty_hints_for("SCP", {scp_id}),
            source="operator",
            event_type="UNMARK",
        )
        self.report({"INFO"}, f"Unmarked SCP '{scp_id}'")
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

        for m in root.af_vcp_system.muscles:
            to_remove = [i for i, ref in enumerate(m.fiber_refs) if ref.fiber_id == fiber_id]
            for i in reversed(to_remove):
                m.fiber_refs.remove(i)

        fibers.remove(idx)

        if root.af_vcp_system.active_vcp_type == "FIBER" and root.af_vcp_system.active_vcp_id == fiber_id:
            root.af_vcp_system.active_vcp_type = "NONE"
            root.af_vcp_system.active_vcp_id = ""

        sync_from_dirty_hints(root=root, scene=context.scene, dirty_hints=dirty_hints_for("FIBER", {fiber_id}))
        self.report({"INFO"}, f"Deleted Fiber '{fiber_id}'")
        return {"FINISHED"}

    def _delete_blob(self, context, root, blob_id):
        blobs = root.af_vcp_system.blobs
        idx = -1
        for i, b in enumerate(blobs):
            if b.id == blob_id:
                idx = i
                break
        if idx < 0:
            self.report({"ERROR"}, f"Blob '{blob_id}' not found.")
            return {"CANCELLED"}

        blobs.remove(idx)

        if root.af_vcp_system.active_vcp_type == "BLOB" and root.af_vcp_system.active_vcp_id == blob_id:
            root.af_vcp_system.active_vcp_type = "NONE"
            root.af_vcp_system.active_vcp_id = ""

        sync_from_dirty_hints(root=root, scene=context.scene, dirty_hints=dirty_hints_for("BLOB", {blob_id}))
        self.report({"INFO"}, f"Deleted Blob '{blob_id}'")
        return {"FINISHED"}

    def execute(self, context):
        root = get_af_root(context.scene)
        if not self.target_id:
            self.target_type = "AUTO"

        if root is None:
            return bpy.ops.object.delete("INVOKE_DEFAULT")

        if self.target_type == "SCP" and self.target_id:
            return self._delete_scp(context, root, self.target_id)
        if self.target_type == "FIBER" and self.target_id:
            return self._delete_fiber(context, root, self.target_id)
        if self.target_type == "BLOB" and self.target_id:
            return self._delete_blob(context, root, self.target_id)

        obj = context.active_object
        if obj is None:
            return bpy.ops.object.delete("INVOKE_DEFAULT")

        if obj.get("af_scp") and not obj.get("af_scp_mirror") and obj.get("af_root_name") == root.name and obj.get("af_scp_id"):
            return self._delete_scp(context, root, obj.get("af_scp_id"))

        if obj.get("af_fiber_proxy") and obj.get("af_root_name") == root.name and obj.get("af_fiber_id"):
            return self._delete_fiber(context, root, obj.get("af_fiber_id"))

        if obj.get("af_blob_proxy") and obj.get("af_root_name") == root.name and obj.get("af_blob_id"):
            return self._delete_blob(context, root, obj.get("af_blob_id"))

        return bpy.ops.object.delete("INVOKE_DEFAULT")
