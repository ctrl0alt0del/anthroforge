import bpy

from ...core.utils import get_af_root


def _is_marked_scp_obj(obj):
    return bool(obj and obj.get("af_scp") and not obj.get("af_scp_mirror") and obj.get("af_scp_id"))


def _active_scp_prop(root, obj):
    if root is None or obj is None:
        return None
    sid = str(obj.get("af_scp_id") or "")
    if not sid:
        return None
    for scp in root.af_scp_system.scps:
        if str(getattr(scp, "id", "") or "") == sid:
            return scp
    return None


class AF_PT_CreatePanel(bpy.types.Panel):
    bl_label = "SCP Marking"
    bl_idname = "AF_PT_create_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return get_af_root(context.scene) is not None

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        root = get_af_root(scene)
        obj = context.active_object

        box = layout.box()
        box.label(text="Mark Existing Mesh As SCP")
        if obj is None:
            box.label(text="No active object", icon="INFO")
        else:
            box.label(text=f"Active: {obj.name}")
            box.label(text=f"Type: {obj.type}")

        row = layout.row(align=True)
        row.operator("af.add_scp", icon="ADD", text="Mark Selected Mesh")

        if _is_marked_scp_obj(obj):
            scp = _active_scp_prop(root, obj)
            op = layout.operator("af.delete_selected_af_node", icon="TRASH", text="Unmark Selected SCP")
            op.target_type = "SCP"
            op.target_id = str(obj.get("af_scp_id"))

            layout.separator()
            pbox = layout.box()
            pbox.label(text="Parent Relation")
            pbox.prop(scene, "af_scp_parent_obj", text="Parent")
            pbox.operator("af.set_scp_parent", text="Apply Parent", icon="CONSTRAINT")

            if scp is not None:
                mbox = layout.box()
                mbox.label(text="Mirror")
                mbox.prop(scp, "mirror_enabled", text="Mirror Children")
                axis_row = mbox.row()
                axis_row.enabled = bool(scp.mirror_enabled)
                axis_row.prop(scp, "mirror_axis", text="Axis")
