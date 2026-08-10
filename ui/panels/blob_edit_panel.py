import bpy
from ...app.queries.root import root_for_context
from ...app.queries.vcp import active_blob_from_context, blob_proxy_for_context, has_active_entity
from ...core.vcp.runtime_state import blob_solve_converged, blob_solve_iterations, blob_solve_max_disp


class AF_PT_BlobEditPanel(bpy.types.Panel):
    bl_label = "Edit Blob VCP"
    bl_idname = "AF_PT_blob_edit_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return root_for_context(context) is not None and has_active_entity(context, "BLOB")

    def _draw_identity(self, layout, blob):
        row = layout.row()
        row.enabled = False
        row.prop(blob, "id", text="ID")
        layout.prop(blob, "name", text="Name")

    def _draw_geometry(self, layout, blob):
        geo = layout.box()
        geo.label(text="Geometry")
        geo.prop(blob, "resolution", text="Resolution")

    def _draw_transform(self, layout, context, blob):
        tfm = layout.box()
        tfm.label(text="Proxy Transform")
        proxy = blob_proxy_for_context(context, blob)
        if proxy is None:
            tfm.label(text="Proxy not found")
            return
        tfm.prop(proxy, "location", text="Location")
        tfm.prop(proxy, "rotation_euler", text="Rotation")
        tfm.prop(proxy, "scale", text="Scale")

    def _draw_control(self, layout, blob):
        ctrl = layout.box()
        ctrl.label(text="Control Point (Ray Target)")
        ctrl.prop(blob, "control_point_world", text="World")
        op = ctrl.operator("af.select_blob_control", text="Select Control Point", icon="EMPTY_ARROWS")
        op.blob_id = blob.id

    def _draw_gravity(self, layout, blob):
        grav = layout.box()
        grav.label(text="Gravity")
        grav.prop(blob, "gravity_dir", text="Direction")
        grav.prop(blob, "sag_strength", text="Sag Strength")
        grav.prop(blob, "sag_limit", text="Sag Limit")

    def _draw_attachment(self, layout, blob):
        att = layout.box()
        att.label(text="Attachment")
        att.prop(blob, "attach_target_type", text="Target Type")
        att.prop(blob, "attach_target_id", text="Target ID")
        att.prop(blob, "attach_target_object_name", text="Target Object")

    def _draw_material(self, layout, blob):
        mat = layout.box()
        mat.label(text="Material")
        mat.prop(blob, "stiffness", text="Stiffness")
        mat.prop(blob, "iterations", text="Iterations")

    def _draw_solver_debug(self, layout, blob):
        dbg = layout.box()
        dbg.label(text="Solver")
        dbg.label(text=f"Converged: {blob_solve_converged(blob)}")
        dbg.label(text=f"Max Disp: {blob_solve_max_disp(blob):.6f}")
        dbg.label(text=f"Iterations Used: {blob_solve_iterations(blob)}")

    def draw(self, context):
        layout = self.layout
        blob = active_blob_from_context(context)
        if blob is None:
            layout.label(text="Blob not found")
            return
        layout.operator("af.convert_blob_to_soft_tissue", icon="FILE_REFRESH")

        self._draw_identity(layout, blob)
        self._draw_geometry(layout, blob)
        self._draw_transform(layout, context, blob)
        self._draw_control(layout, blob)
        self._draw_gravity(layout, blob)
        self._draw_attachment(layout, blob)
        self._draw_material(layout, blob)
        self._draw_solver_debug(layout, blob)
