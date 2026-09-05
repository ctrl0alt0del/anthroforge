import bpy

from ...app.queries.action_library import curve_loft_panel_state, local_transform_panel_state, quick_fiber_panel_state, quick_hook_panel_state, split_corner_panel_state
from ...app.queries.proxy_view import proxy_view_panel_state
from ...app.queries.root import root_for_context
from ...core.visualization.fiber_repair_runtime import fiber_repair_state


def _status_icon(state):
    if state.has_conflict:
        return "ERROR"
    return "CHECKMARK" if state.installed else "INFO"


def _draw_header(box, state):
    box.label(text="Local Transform Properties")
    box.label(text=f"Active: {state.active_name}" if state.has_object else "No active object", icon="OBJECT_DATA")


def _draw_status(box, state):
    box.label(text=state.message, icon=_status_icon(state))
    box.label(text="Created properties can be targeted by shortcuts manually.", icon="DRIVER")


def _draw_buttons(box, state):
    row = box.row(align=True)
    row.enabled = state.has_object and not state.has_conflict
    row.operator("af.create_local_transform_props", icon="ADD")
    row.operator("af.rebind_local_transform_props", icon="FILE_REFRESH")
    row = box.row()
    row.enabled = state.has_object and (state.has_props or state.installed) and not state.has_conflict
    row.operator("af.remove_local_transform_props", icon="X")


def _draw_curve_loft_header(box):
    box.label(text="Curve Loft Geometry Nodes")
    box.label(text="Create a reusable loft node group from N curves.", icon="NODETREE")


def _draw_curve_loft_fields(box, scene):
    box.prop(scene, "af_action_gn_name")
    box.prop(scene, "af_action_curve_count")
    box.prop(scene, "af_action_single_angle")


def _draw_curve_loft_status(box, state):
    icon = "CHECKMARK" if state.can_create else "INFO"
    box.label(text=state.message, icon=icon)


def _draw_curve_loft_button(box, state):
    row = box.row()
    row.enabled = state.can_create
    row.operator("af.create_curve_loft_group", icon="NODETREE")


def _draw_split_corner_header(box):
    box.label(text="Split SCP by Corner")
    box.label(text="Split selected curve corners into SCP segments.", icon="HOOK")


def _draw_quick_hook_header(box):
    box.label(text="Quick Hook")
    box.label(text="Create a native Hook from the current point selection.", icon="HOOK")


def _draw_quick_hook_status(box, state):
    box.label(text=state.message, icon="CHECKMARK" if state.can_create else "INFO")
    if state.reuse_target:
        box.label(text=f"Target: {state.reuse_target}", icon="EMPTY_AXIS")


def _draw_quick_hook_controls(box, scene, state):
    box.prop(scene, "af_action_quick_hook_reuse", text="Reuse Last Hook")
    row = box.row()
    row.enabled = state.can_create
    row.operator("af.quick_scp_hook", text=state.button_text, icon="HOOK")


def _draw_quick_fiber_box(layout, context):
    state = quick_fiber_panel_state(context)
    box = layout.box()
    box.label(text="Quick Fiber")
    box.label(text="Draw fibers directly between visible SCP surfaces.", icon="CURVE_DATA")
    box.label(text=state.message, icon="CHECKMARK" if state.can_create else "INFO")
    row = box.row()
    row.enabled = state.can_create
    row.operator("af.quick_fiber", text="Create Quick Fiber", icon="CURVE_DATA")


def _draw_fiber_utilities_box(layout, context):
    box = layout.box()
    box.label(text="Fiber Utilities")
    box.label(text="Repair the active root or apply file-wide settings.", icon="CURVE_DATA")
    _draw_repair_fibers(box, context)
    box.operator("af.disable_all_fiber_surface_routing", text="Disable Surface Routing for All Fibers", icon="X")


def _draw_repair_fibers(box, context):
    root = root_for_context(context); state = None if root is None else fiber_repair_state(root, context.scene)
    row = box.row(); row.enabled = bool(root and len(root.af_vcp_system.fibers) and not (state or {}).get("active"))
    row.operator("af.repair_fibers", text="Repair Fibers", icon="TOOL_SETTINGS")
    _draw_repair_status(box, state)


def _draw_repair_status(box, state):
    if not state: return
    if state.get("active"): _draw_active_repair_status(box, state); return
    summary = state.get("summary") or state.get("last_summary")
    if summary: box.label(text=summary, icon="CHECKMARK" if state.get("phase") == "DONE" else "INFO")


def _draw_active_repair_status(box, state):
    if state.get("phase") == "SCANNING":
        progress = state.get("progress", {}); box.label(text=f"Scan: {progress.get('current', 0)}/{progress.get('total', 0)}")
        box.label(text=f"Invalid pins found: {state.get('invalid', 0)}", icon="VIEWZOOM")
        return
    group = state.get("group") or {}; total = len(group.get("targets", ()))
    complete = total - len(group.get("pending", ()))
    box.label(text=f"Recompute: {complete}/{total}", icon="FILE_REFRESH")
    box.label(text=f"Successful {len(group.get('committed', ()))} · failed {len(group.get('failures', {}))}")
    box.label(text=f"Pins repaired {state.get('repaired', 0)} · unresolved {state.get('unresolved', 0)}")


def _draw_split_corner_status(box, state):
    box.label(text=state.message, icon="CHECKMARK" if state.can_split else "INFO")
    box.label(text="Run this from Curve Edit Mode on the bound curve object.", icon="OUTLINER_OB_CURVE")


def _draw_split_corner_button(box, state):
    row = box.row()
    row.enabled = state.can_split
    row.operator("af.split_scp_by_corner", icon="SPLIT_HORIZONTAL")


def _draw_proxy_header(box):
    box.label(text="Proxy View")
    box.label(text="Build subtree proxy meshes for vertex-level fiber work.", icon="MESH_DATA")


def _draw_proxy_status(box, state):
    box.label(text=state.message, icon="CHECKMARK" if state.can_switch else "INFO")


def _draw_proxy_buttons(box, state):
    row = box.row(align=True)
    row.enabled = state.can_switch
    row.operator("af.switch_to_proxy_view", icon="MOD_EDGESPLIT")
    exit_row = box.row()
    exit_row.enabled = state.can_exit
    exit_row.operator("af.exit_proxy_view", icon="X")


def _draw_proxy_box(layout, context):
    state = proxy_view_panel_state(context)
    box = layout.box()
    _draw_proxy_header(box)
    _draw_proxy_status(box, state)
    _draw_proxy_buttons(box, state)


def _draw_local_transform_box(layout, context):
    state = local_transform_panel_state(context)
    box = layout.box()
    _draw_header(box, state)
    _draw_status(box, state)
    _draw_buttons(box, state)


def _draw_curve_loft_box(layout, context):
    state = curve_loft_panel_state(context)
    box = layout.box()
    _draw_curve_loft_header(box)
    _draw_curve_loft_fields(box, context.scene)
    _draw_curve_loft_status(box, state)
    _draw_curve_loft_button(box, state)


def _draw_split_corner_box(layout, context):
    state = split_corner_panel_state(context)
    box = layout.box()
    _draw_split_corner_header(box)
    _draw_split_corner_status(box, state)
    _draw_split_corner_button(box, state)


def _draw_quick_hook_box(layout, context):
    state = quick_hook_panel_state(context)
    box = layout.box()
    _draw_quick_hook_header(box)
    _draw_quick_hook_status(box, state)
    _draw_quick_hook_controls(box, context.scene, state)


class AF_PT_ActionLibraryPanel(bpy.types.Panel):
    bl_label = "Action Library"
    bl_idname = "AF_PT_action_library_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    def draw(self, context):
        _draw_local_transform_box(self.layout, context)
        _draw_quick_fiber_box(self.layout, context)
        _draw_fiber_utilities_box(self.layout, context)
        _draw_proxy_box(self.layout, context)
        _draw_curve_loft_box(self.layout, context)
        _draw_quick_hook_box(self.layout, context)
        _draw_split_corner_box(self.layout, context)
