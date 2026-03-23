import bpy
from ...core.utils import get_af_root
from ..context import get_active_af_entity


def _find_blob_proxy(scene, root_name, blob_id):
    for obj in scene.objects:
        if (
            obj.get("af_blob_proxy")
            and obj.get("af_root_name") == root_name
            and obj.get("af_blob_id") == blob_id
            and not obj.get("af_blob_mirror_proxy")
        ):
            return obj
    return None


class AF_PT_BlobEditPanel(bpy.types.Panel):
    bl_label = "Edit Blob VCP"
    bl_idname = "AF_PT_blob_edit_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        root = get_af_root(context.scene)
        if root is None:
            return False
        kind, _entity_id = get_active_af_entity(root, context)
        return kind == "BLOB"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        root = get_af_root(scene)
        v = root.af_vcp_system

        blob = next((b for b in v.blobs if b.id == v.active_vcp_id), None)
        if blob is None:
            layout.label(text="Blob not found")
            return

        row = layout.row()
        row.enabled = False
        row.prop(blob, "id", text="ID")

        layout.prop(blob, "name", text="Name")

        geo = layout.box()
        geo.label(text="Geometry")
        geo.prop(blob, "resolution", text="Resolution")

        tfm = layout.box()
        tfm.label(text="Proxy Transform")
        proxy = _find_blob_proxy(scene, root.name, blob.id)
        if proxy is None:
            tfm.label(text="Proxy not found")
        else:
            tfm.prop(proxy, "location", text="Location")
            tfm.prop(proxy, "rotation_euler", text="Rotation")
            tfm.prop(proxy, "scale", text="Scale")

        ctrl = layout.box()
        ctrl.label(text="Control Point (Ray Target)")
        ctrl.prop(blob, "control_point_world", text="World")
        op = ctrl.operator("af.select_blob_control", text="Select Control Point", icon="EMPTY_ARROWS")
        op.blob_id = blob.id

        grav = layout.box()
        grav.label(text="Gravity")
        grav.prop(blob, "gravity_dir", text="Direction")
        grav.prop(blob, "sag_strength", text="Sag Strength")
        grav.prop(blob, "sag_limit", text="Sag Limit")

        att = layout.box()
        att.label(text="Attachment")
        att.prop(blob, "attach_target_type", text="Target Type")
        att.prop(blob, "attach_target_id", text="Target ID")
        att.prop(blob, "attach_target_object_name", text="Target Object")

        mat = layout.box()
        mat.label(text="Material")
        mat.prop(blob, "stiffness", text="Stiffness")
        mat.prop(blob, "iterations", text="Iterations")

        dbg = layout.box()
        dbg.label(text="Solver")
        dbg.label(text=f"Converged: {blob.last_solve_converged}")
        dbg.label(text=f"Max Disp: {blob.last_solve_max_disp:.6f}")
        dbg.label(text=f"Iterations Used: {blob.last_solve_iterations}")
