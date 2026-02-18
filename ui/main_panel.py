import bpy
from ..core.utils import get_af_root
from ..core.shapes.registry import ShapeRegistry


class AF_PT_MainPanel(bpy.types.Panel):
    bl_label = "AnthroForge"
    bl_idname = "AF_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'AnthroForge'

    def _sync_active_index_from_viewport(self, root, context):
        obj = context.active_object
        if not obj:
            return
        if not obj.get("af_proxy"):
            return
        if obj.get("af_root_name") != root.name:
            return

        scp_id = obj.get("af_scp_id")
        if not scp_id:
            return

        for i, scp in enumerate(root.af_system.scps):
            if scp.id == scp_id:
                if root.af_system.active_scp_index != i:
                    root.af_system.active_scp_index = i
                return

    def _get_active_scp(self, root):
        idx = root.af_system.active_scp_index
        if 0 <= idx < len(root.af_system.scps):
            return root.af_system.scps[idx]
        return None

    def draw(self, context):
        layout = self.layout
        root = get_af_root(context.scene)

        # ------------------------------
        # No Root
        # ------------------------------
        if root is None:
            layout.label(text="No AF_ROOT in scene", icon='ERROR')
            layout.operator("af.create_root", icon='ADD')
            return

        # ------------------------------
        # SCP Creation
        # ------------------------------
        layout.label(text="SCP Creation", icon='MESH_ICOSPHERE')

        col = layout.column()
        col.prop(context.scene, "af_scp_type", text="Shape")

        create_box = layout.box()
        create_box.label(text="New SCP Params")
        ShapeRegistry.draw_creation_ui(
            context.scene.af_scp_type,
            create_box,
            context.scene
        )

        layout.operator("af.add_scp", icon='ADD')
        layout.separator()

        # ------------------------------
        # SCP List
        # ------------------------------
        layout.label(text="SCP List")
        layout.template_list(
            "AF_UL_SCPList",
            "",
            root.af_system,
            "scps",
            root.af_system,
            "active_scp_index"
        )

        # Keep list selection synced with selected proxy in viewport
        self._sync_active_index_from_viewport(root, context)

        scp = self._get_active_scp(root)
        if not scp:
            return

        # ------------------------------
        # SCP Edit
        # ------------------------------
        layout.separator()
        box = layout.box()
        box.label(text="Edit SCP", icon='MODIFIER')

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
        # set readonly=False if you want editable after creation
        ShapeRegistry.draw_scp_ui(
            scp.shape_type,
            box,
            scp,
            readonly=True
        )
