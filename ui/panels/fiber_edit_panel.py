import bpy
from ...core.utils import get_af_root


class AF_PT_FiberEditPanel(bpy.types.Panel):
    bl_label = "Fiber Settings"
    bl_idname = "AF_PT_fiber_edit_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return get_af_root(context.scene) is not None

    def draw(self, context):
        layout = self.layout
        root = get_af_root(context.scene)
        vcp = root.af_vcp_system

        if vcp.active_vcp_type != "FIBER" or not vcp.active_vcp_id:
            layout.label(text="Select a Fiber in VCP Tree")
            return

        fiber = None
        for f in vcp.fibers:
            if f.id == vcp.active_vcp_id:
                fiber = f
                break

        if fiber is None:
            layout.label(text="Fiber not found")
            return

        layout.label(text=fiber.id, icon="CURVE_DATA")

        box = layout.box()
        box.label(text="Endpoints")
        box.label(text=f"Origin: {fiber.a_parent_id or '-'}")
        box.label(text=f"Insertion: {fiber.b_parent_id or '-'}")

        box = layout.box()
        box.label(text="Solver")
        box.prop(fiber, "node_count")
        box.prop(fiber, "rest_length")
        op = box.operator("af.reset_fiber_rest_length", icon="FILE_REFRESH")
        op.fiber_id = fiber.id

        box.prop(fiber, "iterations_interactive")
        box.prop(fiber, "iterations_bake")

        box.prop(fiber, "stretch_enabled")
        box.prop(fiber, "max_stretch")
        box.prop(fiber, "stretch_stiffness")
        box.prop(fiber, "bend_stiffness")
        box.prop(fiber, "collision_margin")
        box.prop(fiber, "damping")

        box = layout.box()
        box.label(text="Display")
        box.prop(fiber, "thickness")
        status = fiber.last_recompute_status
        if status == "CONVERGED":
            box.label(text="Status: Converged", icon="CHECKMARK")
        elif status == "NOT_CONVERGED":
            box.label(text="Status: Not Converged", icon="ERROR")
        else:
            box.label(text="Status: Unknown", icon="QUESTION")
        if fiber.last_recompute_status == "NOT_CONVERGED":
            box.label(text=f"Residual disp: {fiber.last_eps_disp:.6f}")
            box.label(text=f"Residual pen: {fiber.last_eps_pen:.6f}")
        box.label(text=f"Recompute: {fiber.last_recompute_ms:.2f} ms")
        box.prop(fiber, "use_warm_start")
        layout.operator("af.recompute_fiber", icon="FILE_REFRESH")
