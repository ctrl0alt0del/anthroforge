import bpy

from ...core.deps.controls import is_control_object
from ...core.utils import get_af_root
from ...operators.control_objects import has_axis_shortcut


def _active_object(context):
    return getattr(context, "active_object", None)


def _draw_checkbox_row(layout, axis, checked):
    icon = "CHECKBOX_HLT" if checked else "CHECKBOX_DEHLT"
    row = layout.row(align=True)
    op = row.operator("af.toggle_control_object_shortcut_axis", text=f"Position {axis}", icon=icon)
    op.axis = axis


def _draw_shortcut_checkbox_mode(layout, root, obj):
    box = layout.box()
    box.label(text=f"Control Object: {obj.name}", icon="CON_OBJECTSOLVER")
    box.label(text="Position Components")
    for axis in ("X", "Y", "Z"):
        _draw_checkbox_row(box, axis, has_axis_shortcut(root, obj, axis))


def _draw_mark_mode(layout, context, obj):
    box = layout.box()
    box.label(text="Mark Control Object", icon="OUTLINER_OB_EMPTY")
    if obj is None:
        box.label(text="Select an object first.", icon="INFO")
        return

    box.prop(context.scene, "af_control_scp_obj", text="SCP")
    picked = getattr(context.scene, "af_control_scp_obj", None)
    if picked is None:
        box.label(text="Pick an SCP object first.", icon="ERROR")
        return

    box.label(text=f"Selected Object: {obj.name}")
    box.label(text=f"Target SCP: {picked.name}")
    box.operator("af.mark_selected_scp_control_object", icon="ADD")


class AFPTControlObjectsPanel(bpy.types.Panel):
    bl_label = "Control Objects"
    bl_idname = "AF_PT_control_objects_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return get_af_root(context.scene) is not None

    def draw(self, context):
        root = get_af_root(context.scene)
        obj = _active_object(context)
        if obj is not None and is_control_object(obj):
            _draw_shortcut_checkbox_mode(self.layout, root, obj)
            return
        _draw_mark_mode(self.layout, context, obj)
