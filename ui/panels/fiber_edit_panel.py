import bpy
from ...core.utils import get_af_root
from ..context import get_active_af_entity

def _scp_label(root, scp_id):
    if not scp_id:
        return "-"
    for scp in root.af_scp_system.scps:
        if scp.id == scp_id:
            return scp.name if getattr(scp, "name", "") else scp.id
    return f"{scp_id} (missing)"


class AF_PT_FiberEditPanel(bpy.types.Panel):
    bl_label = "Edit Fiber VCP"
    bl_idname = "AF_PT_fiber_edit_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        root_is_valid = get_af_root(context.scene) is not None
        has_fiber_selected = get_active_af_entity(get_af_root(context.scene), context)[0] == "FIBER"
        return root_is_valid and has_fiber_selected

    def _active_fiber(self, vcp):
        for f in vcp.fibers:
            if f.id == vcp.active_vcp_id:
                return f
        return None

    def _draw_endpoints(self, layout, root, fiber):
        endpoints_box = layout.box()
        endpoints_box.label(text="Endpoints")
        endpoints_box.label(text=f"Origin: {_scp_label(root, fiber.a_parent_id)}")
        endpoints_box.label(text=f"Insertion: {_scp_label(root, fiber.b_parent_id)}")

    def _draw_solver(self, layout, fiber):
        solver_box = layout.box()
        solver_box.label(text="Solver")
        solver_box.prop(fiber, "use_warm_start")
        op = solver_box.operator("af.clear_fiber_warm_start", icon="TRASH")
        op.fiber_id = fiber.id
        layout.prop(fiber, "name", text="Name")
        solver_box.prop(fiber, "node_count")
        solver_box.prop(fiber, "iterations_interactive")
        solver_box.prop(fiber, "iterations_bake")
        solver_box.prop(fiber, "bend_stiffness")
        solver_box.prop(fiber, "collision_margin")
        solver_box.prop(fiber, "damping")
        if hasattr(fiber, "guide_stiffness"):
            solver_box.prop(fiber, "guide_stiffness")

    def _draw_touch_points(self, layout, root, fiber):
        touch_box = layout.box()
        touch_box.label(text="Mid Touch Points")
        touch_box.label(text="Select SCP, then add")
        op = touch_box.operator("af.add_fiber_touch_point", icon="ADD")
        op.fiber_id = fiber.id
        for i, tp in enumerate(fiber.mid_touches):
            row = touch_box.row(align=True)
            row.label(text=f"{i + 1}. {_scp_label(root, tp.parent_id)}")
            op = row.operator("af.remove_fiber_touch_point", text="", icon="X")
            op.fiber_id = fiber.id
            op.touch_index = i

    def _draw_status(self, layout, fiber):
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

    def _draw_display(self, layout, fiber):
        display_box = layout.box()
        display_box.label(text="Display")
        display_box.prop(fiber, "thickness")
        op = layout.operator("af.recompute_fiber", icon="FILE_REFRESH")
        op.fiber_id = fiber.id

    def draw(self, context):
        layout = self.layout
        root = get_af_root(context.scene)
        vcp = root.af_vcp_system

        kind, active_id = get_active_af_entity(root, context)
        if kind != "FIBER" or not active_id:
            layout.label(text="Select a Fiber")
            return

        fiber = self._active_fiber(vcp)
        if fiber is None:
            layout.label(text="Fiber not found")
            return

        layout.label(text=fiber.id, icon="CURVE_DATA")
        self._draw_endpoints(layout, root, fiber)
        self._draw_solver(layout, fiber)
        self._draw_touch_points(layout, root, fiber)
        self._draw_status(layout, fiber)
        self._draw_display(layout, fiber)
