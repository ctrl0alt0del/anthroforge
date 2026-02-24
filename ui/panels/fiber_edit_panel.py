# ui/panels/fiber_edit_panel.py
import bpy
from ...core.utils import get_af_root


def _scp_label(root, scp_id):
    if not scp_id:
        return "-"
    for scp in root.af_scp_system.scps:
        if scp.id == scp_id:
            return scp.name if getattr(scp, "name", "") else scp.id
    return f"{scp_id} (missing)"


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

        endpoints_box = layout.box()
        endpoints_box.label(text="Endpoints")
        endpoints_box.label(text=f"Origin: {_scp_label(root, fiber.a_parent_id)}")
        endpoints_box.label(text=f"Insertion: {_scp_label(root, fiber.b_parent_id)}")

        solver_box = layout.box()
        solver_box.label(text="Solver")
        solver_box.prop(fiber, "use_warm_start")
        solver_box.prop(fiber, "node_count")
        solver_box.prop(fiber, "rest_length")

        op = solver_box.operator("af.reset_fiber_rest_length", icon="FILE_REFRESH")
        op.fiber_id = fiber.id

        solver_box.prop(fiber, "iterations_interactive")
        solver_box.prop(fiber, "iterations_bake")

        solver_box.prop(fiber, "stretch_enabled")
        solver_box.prop(fiber, "max_stretch")
        solver_box.prop(fiber, "stretch_stiffness")
        solver_box.prop(fiber, "bend_stiffness")
        solver_box.prop(fiber, "collision_margin")
        solver_box.prop(fiber, "damping")
        solver_box.prop(fiber, "guide_stiffness")

        touch_box = layout.box()
        touch_box.label(text="Mid Touch Points")
        touch_box.label(text="Select SCP, then add touch point")

        op = touch_box.operator("af.add_fiber_touch_point", icon="ADD")
        op.fiber_id = fiber.id

        for i, tp in enumerate(fiber.mid_touches):
            row = touch_box.row(align=True)
            row.label(text=f"{i + 1}. {_scp_label(root, tp.parent_id)}")
            op = row.operator("af.remove_fiber_touch_point", text="", icon="X")
            op.fiber_id = fiber.id
            op.touch_index = i

        status_box = layout.box()
        status = fiber.last_recompute_status
        if status == "CONVERGED":
            status_box.label(text="Status: Converged", icon="CHECKMARK")
        elif status == "NOT_CONVERGED":
            status_box.label(text="Status: Not Converged", icon="ERROR")
            status_box.label(text=f"Residual disp: {fiber.last_eps_disp:.6f}")
            status_box.label(text=f"Residual pen: {fiber.last_eps_pen:.6f}")
        else:
            status_box.label(text="Status: Unknown", icon="QUESTION")

        status_box.label(text=f"Recompute: {fiber.last_recompute_ms:.2f} ms")

        display_box = layout.box()
        display_box.label(text="Display")
        display_box.prop(fiber, "thickness")

        op = solver_box.operator("af.clear_fiber_warm_start", icon="TRASH")
        op.fiber_id = fiber.id
        op = layout.operator("af.recompute_fiber", icon="FILE_REFRESH")
        op.fiber_id = fiber.id
