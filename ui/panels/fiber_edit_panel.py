import bpy
from ...app.queries.root import root_for_context
from ...app.queries.scp import scp_label
from ...app.queries.vcp import active_fiber_from_context, has_active_entity
from ...core.vcp.fiber_modes import is_loop_fiber, is_solved_loop
from ...core.vcp.runtime_state import (
    fiber_active_colliders,
    fiber_eps_disp,
    fiber_eps_pen,
    fiber_invalid_reason,
    fiber_planner_ms,
    fiber_recompute_ms,
    fiber_recompute_status,
    fiber_refine_ms,
    fiber_route_mode,
)


class AF_PT_FiberEditPanel(bpy.types.Panel):
    bl_label = "Edit Fiber VCP"
    bl_idname = "AF_PT_fiber_edit_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return root_for_context(context) is not None and has_active_entity(context, "FIBER")

    def _draw_endpoints(self, layout, root, fiber):
        endpoints_box = layout.box()
        endpoints_box.label(text="Endpoints")
        endpoints_box.label(text=f"Origin: {scp_label(root, fiber.a_parent_id)}")
        endpoints_box.label(text=f"Insertion: {scp_label(root, fiber.b_parent_id)}")

    def _draw_loop_anchors(self, layout, root, fiber):
        box = layout.box()
        box.label(text="Loop Anchors")
        box.label(text=f"Seam: {scp_label(root, fiber.loop_anchors[0].parent_id) if fiber.loop_anchors else 'Missing'}")
        for i, anchor in enumerate(fiber.loop_anchors):
            box.label(text=f"{i + 1}. {scp_label(root, anchor.parent_id)}")

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

    def _draw_touch_points(self, layout, root, fiber):
        touch_box = layout.box()
        touch_box.label(text="Mid Touch Points")
        touch_box.label(text="Select SCP, then add")
        op = touch_box.operator("af.add_fiber_touch_point", icon="ADD")
        op.fiber_id = fiber.id
        for i, tp in enumerate(fiber.mid_touches):
            self._draw_touch_point(touch_box, root, fiber, i, tp)

    def _draw_touch_point(self, layout, root, fiber, index, touch):
        row = layout.row(align=True)
        row.label(text=f"{index + 1}. {scp_label(root, touch.parent_id)}")
        op = row.operator("af.remove_fiber_touch_point", text="", icon="X")
        op.fiber_id, op.touch_index = fiber.id, index
        self._draw_touch_offset(layout, touch)

    def _draw_touch_offset(self, layout, touch):
        row = layout.row(align=True)
        row.prop(touch, "normal_offset", text="Offset")

    def _draw_invalid_status(self, status_box, fiber):
        reason = fiber_invalid_reason(fiber)
        if not reason:
            return False
        status_box.label(text="Status: Invalid Attachment", icon="ERROR")
        status_box.label(text=reason)
        return True

    def _draw_status(self, layout, fiber):
        status_box = layout.box()
        self._draw_status_header(status_box, fiber)
        self._draw_status_metrics(status_box, fiber)

    def _draw_status_header(self, status_box, fiber):
        if self._draw_invalid_status(status_box, fiber):
            return
        status = fiber_recompute_status(fiber)
        if status == "CONVERGED":
            status_box.label(text="Status: Converged", icon="CHECKMARK")
            return
        if status == "NOT_CONVERGED":
            status_box.label(text="Status: Not Converged", icon="ERROR")
            status_box.label(text=f"Residual disp: {fiber_eps_disp(fiber):.6f}")
            status_box.label(text=f"Residual pen: {fiber_eps_pen(fiber):.6f}")
            return
        status_box.label(text="Status: Unknown", icon="QUESTION")

    def _draw_status_metrics(self, status_box, fiber):
        status_box.label(text=f"Recompute: {fiber_recompute_ms(fiber):.2f} ms")
        status_box.label(text=f"Route: {fiber_route_mode(fiber)}")
        status_box.label(text=f"Planner: {fiber_planner_ms(fiber):.2f} ms")
        status_box.label(text=f"Refine: {fiber_refine_ms(fiber):.2f} ms")
        status_box.label(text=f"Active Colliders: {fiber_active_colliders(fiber)}")

    def _draw_display(self, layout, fiber):
        display_box = layout.box()
        display_box.label(text="Display")
        display_box.prop(fiber, "thickness")
        op = layout.operator("af.recompute_fiber", icon="FILE_REFRESH")
        op.fiber_id = fiber.id

    def _draw_header(self, layout, fiber):
        suffix = "Loop" if is_loop_fiber(fiber) else "Open"
        layout.label(text=f"{fiber.id} ({suffix})", icon="CURVE_DATA")

    def _draw_mode_layout(self, layout, root, fiber):
        if is_solved_loop(fiber):
            self._draw_solved_loop_mode(layout, root, fiber)
            return
        self._draw_open_mode(layout, root, fiber)

    def _draw_solved_loop_mode(self, layout, root, fiber):
        self._draw_loop_anchors(layout, root, fiber)
        self._draw_solver(layout, fiber)
        self._draw_status(layout, fiber)
        self._draw_display(layout, fiber)

    def _draw_open_mode(self, layout, root, fiber):
        self._draw_endpoints(layout, root, fiber)
        self._draw_solver(layout, fiber)
        self._draw_touch_points(layout, root, fiber)
        self._draw_status(layout, fiber)
        self._draw_display(layout, fiber)

    def draw(self, context):
        layout = self.layout
        root = root_for_context(context)
        fiber = active_fiber_from_context(context)
        if fiber is None:
            layout.label(text="Fiber not found")
            return

        self._draw_header(layout, fiber)
        self._draw_mode_layout(layout, root, fiber)
