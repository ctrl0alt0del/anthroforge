import bpy
from ...core.utils import get_af_root
from ..context import get_active_af_entity


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
        root = get_af_root(context.scene)
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
        geo.prop(blob, "center_world", text="Center")
        geo.prop(blob, "radius", text="Radius")
        geo.prop(blob, "shape", text="Shape")
        if blob.shape == "ELLIPSOID":
            geo.prop(blob, "axis_scale", text="Axis Scale")
        geo.prop(blob, "resolution", text="Control Points")

        grav = layout.box()
        grav.label(text="Gravity")
        grav.prop(blob, "gravity_dir", text="Direction")
        grav.prop(blob, "sag_strength", text="Sag Strength")
        grav.prop(blob, "sag_limit", text="Sag Limit")

        att = layout.box()
        att.label(text="Attachment")
        att.prop(blob, "attach_mode", text="Mode")
        att.prop(blob, "attach_target_type", text="Target Type")
        att.prop(blob, "attach_target_id", text="Target ID")
        att.prop(blob, "attach_target_object_name", text="Target Object")
        att.prop(blob, "attach_strength", text="Strength")
        att.prop(blob, "attach_falloff_radius", text="Falloff Radius")

        patch = layout.box()
        patch.label(text="Dynamic Patch")
        patch.prop(blob, "blob_contact_margin", text="Contact Margin")
        patch.prop(blob, "blob_penetration_max", text="Penetration Max")
        patch.prop(blob, "blob_patch_exit_scale", text="Exit Scale")
        patch.prop(blob, "blob_patch_max_vertices", text="Max Vertices")

        mat = layout.box()
        mat.label(text="Material")
        mat.prop(blob, "stiffness", text="Stiffness")
        mat.prop(blob, "volume_preserve", text="Volume Preserve")
        mat.prop(blob, "iterations", text="Iterations")

        inf = layout.box()
        inf.label(text="Influence")
        inf.prop(blob, "influence_radius", text="Radius")
        inf.prop(blob, "influence_strength", text="Strength")

        dbg = layout.box()
        dbg.label(text="Solver")
        dbg.label(text=f"Converged: {blob.last_solve_converged}")
        dbg.label(text=f"Max Disp: {blob.last_solve_max_disp:.6f}")
        dbg.label(text=f"Iterations Used: {blob.last_solve_iterations}")
        dbg.label(text=f"Patch Size: {blob.last_patch_size}")
