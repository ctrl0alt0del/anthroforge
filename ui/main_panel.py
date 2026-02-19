# ui/main_panel.py
import bpy
from ..core.utils import get_af_root
from ..core.shapes.registry import ShapeRegistry


class AF_PT_MainPanel(bpy.types.Panel):
    bl_label = "AnthroForge"
    bl_idname = "AF_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"

    def _get_active_scp(self, root, context):
        # Prefer active viewport proxy (read-only lookup, no writes)
        obj = context.active_object
        if obj and obj.get("af_proxy") and obj.get("af_root_name") == root.name:
            scp_id = obj.get("af_scp_id")
            if scp_id:
                for scp in root.af_system.scps:
                    if scp.id == scp_id:
                        return scp

        # Fallback to UI list selection
        idx = root.af_system.active_scp_index
        if 0 <= idx < len(root.af_system.scps):
            return root.af_system.scps[idx]

        return None

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        root = get_af_root(scene)

        if root is None:
            layout.label(text="No AF_ROOT in scene", icon="ERROR")
            layout.operator("af.create_root", icon="ADD")
            return

        # SCP Creation
        layout.label(text="SCP Creation", icon="MESH_ICOSPHERE")
        layout.prop(scene, "af_scp_type", text="Shape")

        create_box = layout.box()
        create_box.label(text="New SCP Params")
        create_box.prop(scene, "af_new_parent_obj", text="Parent")
        ShapeRegistry.draw_creation_ui(scene.af_scp_type, create_box, scene)

        layout.operator("af.add_scp", icon="ADD")
        layout.separator()

        # SCP List
        layout.label(text="SCP List")
        layout.template_list(
            "AF_UL_SCPList",
            "",
            root.af_system,
            "scps",
            root.af_system,
            "active_scp_index",
        )

        # SCP Edit
        scp = self._get_active_scp(root, context)
        if not scp:
            return

        layout.separator()
        box = layout.box()
        box.label(text="Edit SCP", icon="MODIFIER")

        row = box.row()
        row.prop(scp, "id")

        row = box.row()
        row.enabled = False
        row.prop(scp, "shape_type", text="Shape")

        box.separator()
        box.label(text="Transform")
        box.prop(scp, "local_origin")
        box.prop(scp, "local_rotation_euler")
        box.prop(scp, "local_scale")

        box.separator()
        box.label(text="Shape Params")
        ShapeRegistry.draw_scp_ui(scp.shape_type, box, scp, readonly=True)
