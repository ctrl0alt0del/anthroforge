import bpy
from ...app.queries.root import root_for_context
from ...app.queries.scp import scp_label
from ...app.queries.vcp import active_fiber_from_context, has_active_entity
from ...core.vcp.fiber_modes import is_loop_fiber, is_solved_loop
from ...core.vcp.fiber_anchor_preflight import (anchor_preflight_summary,
                                                current_fiber_anchor_preflight)
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


_STATUS_LABELS = {
    "UNKNOWN": ("Not Evaluated This Session", "QUESTION"),
    "REFINING": ("Refining", "TIME"), "CONVERGED": ("Converged", "CHECKMARK"),
    "PLANNER_PREVIEW": ("Planner Preview", "HIDE_OFF"),
    "NO_FEASIBLE_PATH": ("No Feasible Planner Path", "ERROR"),
    "NOT_CONVERGED": ("Not Converged", "ERROR"), "STALLED": ("Stalled", "ERROR"),
    "BLOCKED": ("Blocked", "ERROR"), "BUDGET_EXHAUSTED": ("Budget Exhausted", "TIME"),
    "UNSAFE_OUTPUT": ("Unsafe Output", "ERROR"),
    "BACKEND_UNAVAILABLE": ("Backend Unavailable", "ERROR"),
    "INVALID_CONFIGURATION": ("Invalid Configuration", "ERROR"),
    "INVALID_ATTACHMENT": ("Invalid Attachment", "ERROR"),
    "CANCELLED": ("Cancelled", "CANCEL"), "SUPERSEDED": ("Superseded", "CANCEL"),
}


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
        solver_box.label(text=f"Solver V{int(fiber.solver_version)}")
        solver_box.prop(fiber, "use_warm_start")
        solver_box.prop(fiber, "use_surface_routing")
        solver_box.prop(fiber, "use_segment_collisions")
        solver_box.prop(fiber, "preview_planner_route")
        op = solver_box.operator("af.clear_fiber_warm_start", icon="TRASH")
        op.fiber_id = fiber.id
        layout.prop(fiber, "name", text="Name")
        solver_box.prop(fiber, "node_count")
        solver_box.prop(fiber, "iterations_interactive")
        solver_box.prop(fiber, "iterations_bake")
        solver_box.prop(fiber, "collision_radius")
        self._draw_weights(solver_box, fiber)

    def _draw_weights(self, layout, fiber):
        if int(fiber.solver_version) >= 2:
            layout.prop(fiber, "stretch_stiffness", text="Length Weight")
            layout.prop(fiber, "bend_stiffness", text="Curvature Weight")
            return
        layout.prop(fiber, "stretch_stiffness")
        layout.prop(fiber, "bend_stiffness")

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
        self._draw_touch_move_button(row, fiber, index, -1, "TRIA_UP", index > 0)
        self._draw_touch_move_button(row, fiber, index, 1, "TRIA_DOWN", index < len(fiber.mid_touches) - 1)
        op = row.operator("af.remove_fiber_touch_point", text="", icon="X")
        op.fiber_id, op.touch_index = fiber.id, index
        self._draw_touch_offset(layout, touch)

    def _draw_touch_move_button(self, row, fiber, index, direction, icon, enabled):
        slot = row.row(align=True)
        slot.enabled = bool(enabled)
        op = slot.operator("af.move_fiber_touch_point", text="", icon=icon)
        op.fiber_id, op.touch_index, op.direction = fiber.id, index, direction

    def _draw_touch_offset(self, layout, touch):
        row = layout.row(align=True)
        row.prop(touch, "normal_offset", text="Offset")

    def _draw_invalid_status(self, status_box, scene, root, fiber):
        preflight = current_fiber_anchor_preflight(scene, root, fiber)
        if preflight is not None and not preflight.valid:
            self._draw_anchor_preflight(status_box, preflight)
            return True
        reason = fiber_invalid_reason(fiber)
        if not reason:
            return False
        status_box.label(text="Status: Invalid Attachment", icon="ERROR")
        status_box.label(text=reason)
        return True

    def _draw_anchor_preflight(self, box, result):
        box.label(text="Status: Invalid Attachment", icon="ERROR")
        box.label(text=anchor_preflight_summary(result))
        for violation in result.violations:
            self._draw_anchor_violation(box, violation)

    def _draw_anchor_violation(self, layout, violation):
        box = layout.box()
        role = self._anchor_role_label(violation)
        relation = str(violation.relation).replace("_", " ").title()
        box.label(text=f"{role} | Owner {violation.owner_id} | {relation} blocker {violation.blocker_id}")
        self._draw_anchor_clearance(box, violation)
        box.label(text=f"Action: {violation.action}")

    def _draw_anchor_clearance(self, box, violation):
        if violation.contained:
            box.label(text="Inside blocker: containment invalidates this anchor.", icon="ERROR")
            return
        text = f"Clearance {violation.measured_clearance:.4f} m / required {violation.configured_clearance:.4f} m"
        box.label(text=text)

    def _anchor_role_label(self, violation):
        role = violation.role.value
        if role == "TOUCH":
            return f"Touch {violation.authored_index}"
        if role == "LOOP":
            return f"Loop {violation.authored_index + 1}"
        return "Endpoint A" if role == "ENDPOINT_A" else "Endpoint B"

    def _draw_status(self, layout, scene, root, fiber):
        status_box = layout.box()
        self._draw_status_header(status_box, scene, root, fiber)
        self._draw_status_metrics(status_box, fiber)

    def _draw_status_header(self, status_box, scene, root, fiber):
        if self._draw_invalid_status(status_box, scene, root, fiber):
            return
        status = fiber_recompute_status(fiber)
        if self._draw_known_status(status_box, fiber, status):
            return
        status_box.label(text="Status: Unknown", icon="QUESTION")

    def _draw_known_status(self, box, fiber, status):
        if status not in _STATUS_LABELS:
            return False
        text, icon = _STATUS_LABELS[status]
        box.label(text=f"Status: {text}", icon=icon)
        self._draw_residuals(box, fiber) if status == "NOT_CONVERGED" else None
        return True

    def _draw_residuals(self, box, fiber):
        box.label(text=f"Residual disp: {fiber_eps_disp(fiber):.6f}")
        box.label(text=f"Residual pen: {fiber_eps_pen(fiber):.6f}")

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
        if fiber.legacy_points_json:
            restore = layout.operator("af.restore_legacy_fiber", icon="LOOP_BACK")
            restore.fiber_id = fiber.id

    def _draw_header(self, layout, fiber):
        suffix = "Loop" if is_loop_fiber(fiber) else "Open"
        layout.label(text=f"{fiber.id} ({suffix})", icon="CURVE_DATA")

    def _draw_mode_layout(self, layout, scene, root, fiber):
        layout.prop(fiber, 'behavior_mode')
        if fiber.behavior_mode == 'FREE': return _draw_free(layout, scene, root, fiber)
        if is_solved_loop(fiber):
            self._draw_solved_loop_mode(layout, scene, root, fiber)
            return
        self._draw_open_mode(layout, scene, root, fiber)

    def _draw_solved_loop_mode(self, layout, scene, root, fiber):
        self._draw_loop_anchors(layout, root, fiber)
        self._draw_solver(layout, fiber)
        self._draw_status(layout, scene, root, fiber)
        self._draw_display(layout, fiber)

    def _draw_open_mode(self, layout, scene, root, fiber):
        self._draw_endpoints(layout, root, fiber)
        self._draw_solver(layout, fiber)
        self._draw_touch_points(layout, root, fiber)
        self._draw_status(layout, scene, root, fiber)
        self._draw_display(layout, fiber)

    def draw(self, context):
        layout = self.layout
        root = root_for_context(context)
        fiber = active_fiber_from_context(context)
        if fiber is None:
            layout.label(text="Fiber not found")
            return

        self._draw_header(layout, fiber)
        self._draw_mode_layout(layout, context.scene, root, fiber)


def _draw_free(layout, scene, root, fiber):
    from ...adapters.free_fiber_editor import state
    layout.prop(fiber, 'name'); layout.prop(fiber, 'free_sampling_resolution'); layout.prop(fiber, 'thickness')
    session = state(root, fiber)
    actions = [('EDIT', 'Edit Path')] if not session else [('APPLY', 'Apply'), ('CANCEL', 'Cancel'), ('BEZIER', 'Convert to Bézier'), ('RESAMPLE', 'Resample Preview')]
    if session and session['stale']: actions = [('REFRESH', 'Refresh'), ('REBASE', 'Rebase Preview'), ('CANCEL', 'Discard')]
    for action, label in actions:
        operator = layout.operator('af.free_fiber_path', text=label); operator.action = action; operator.fiber_id = fiber.id
    layout.label(text='Stale draft: refresh or review a rebase.' if session and session['stale'] else 'Free path — no solver')
    if session and session.get('recovery'): layout.label(text=f"{len(session['recovery'])} previous draft(s) retained for recovery")
    error = fiber_invalid_reason(fiber)
    layout.label(text=error or 'Attachments resolved' if fiber_recompute_status(fiber) == 'FREE_UPDATED' else error or 'Attachment update required', icon='ERROR' if error else 'INFO')
