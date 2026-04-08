import bpy
from ...core.utils import get_af_root
from ...core.shapes.registry import ShapeRegistry
from ..context import get_active_scp, get_active_af_entity


class AF_PT_EditPanel(bpy.types.Panel):
    bl_label = "Edit SCP"
    bl_idname = "AF_PT_edit_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        root = get_af_root(context.scene)
        if root is None:
            return False
        kind, _ = get_active_af_entity(root, context)
        return kind == "SCP"

    def _draw_identity(self, layout, scp):
        row = layout.row()
        row.enabled = False
        row.prop(scp, "id", text="ID")
        layout.prop(scp, "name", text="Name")
        row = layout.row()
        row.enabled = False
        row.prop(scp, "shape_type", text="Shape")

    def _draw_transform(self, layout, scp):
        layout.separator()
        layout.label(text="Transform")
        layout.prop(scp, "local_origin")
        layout.prop(scp, "local_rotation_euler")
        layout.prop(scp, "local_scale")

    def _draw_mirror(self, layout, scp):
        layout.separator()
        layout.label(text="Mirror")
        layout.prop(scp, "mirror_enabled", text="Enabled")
        mcol = layout.column()
        mcol.enabled = bool(scp.mirror_enabled)
        mcol.prop(scp, "mirror_axis", text="Axis")
        mcol.prop(scp, "mirror_origin", text="Origin")

    def _draw_shape_params(self, layout, scp):
        layout.separator()
        layout.label(text="Shape Params")
        editable_shapes = {"CURVE", "PARALLELEPIPED", "ELLIPSOID"}
        ShapeRegistry.draw_scp_ui(scp.shape_type, layout, scp, readonly=(scp.shape_type not in editable_shapes))

    def _draw_constraints_header(self, layout, scp):
        layout.separator()
        layout.label(text="Constraints")
        row = layout.row(align=True)
        add_op = row.operator("af.add_scp_constraint", icon="ADD", text="Add")
        add_op.scp_id = scp.id
        if len(scp.constraints) > 0:
            rm_op = row.operator("af.remove_scp_constraint", icon="REMOVE", text="Remove")
            rm_op.index = scp.active_constraint_index
            rm_op.scp_id = scp.id

    def _draw_constraint_source(self, box, c):
        box.prop(c, "source_obj", text="Source SCP")
        if c.source_scp_id:
            rid = box.row()
            rid.enabled = False
            rid.prop(c, "source_scp_id", text="Resolved ID")
        box.prop(c, "calculator_type", text="Calculator")

    def _draw_constraint_mapping(self, box, c):
        if c.calculator_type == "ARC_BRIDGE":
            box.prop(c, "arc_source_width_prop", text="Source Width")
            box.prop(c, "arc_dest_angle_prop", text="Destination Angle")
            row = box.row(align=True)
            row.prop(c, "arc_width_scale")
            row.prop(c, "arc_width_offset")
            box.prop(c, "arc_full_angle")
            return
        box.prop(c, "source_prop", text="Source")
        box.prop(c, "dest_prop", text="Destination")

    def _draw_constraint_calculator(self, box, c):
        if c.calculator_type == "RANGE_REMAP":
            row = box.row(align=True)
            row.prop(c, "in_min")
            row.prop(c, "in_max")
            row = box.row(align=True)
            row.prop(c, "out_min")
            row.prop(c, "out_max")
            box.prop(c, "clamp")
        elif c.calculator_type == "LINEAR":
            row = box.row(align=True)
            row.prop(c, "linear_a")
            row.prop(c, "linear_b")

    def _draw_constraint_runtime(self, box, c):
        srow = box.row()
        srow.enabled = False
        srow.prop(c, "runtime_status", text="Runtime")
        if c.runtime_message:
            mrow = box.row()
            mrow.enabled = False
            mrow.label(text=c.runtime_message, icon="INFO")

    def _draw_constraint_item(self, layout, scp, index, c):
        box = layout.box()
        hdr = box.row(align=True)
        hdr.prop(c, "enabled", text="")
        hdr.prop(c, "priority", text="Prio")
        del_op = hdr.operator("af.remove_scp_constraint", text="", icon="TRASH")
        del_op.index = index
        del_op.scp_id = scp.id
        self._draw_constraint_source(box, c)
        self._draw_constraint_mapping(box, c)
        self._draw_constraint_calculator(box, c)
        self._draw_constraint_runtime(box, c)

    def draw(self, context):
        layout = self.layout
        root = get_af_root(context.scene)

        scp = get_active_scp(root, context)
        if not scp:
            layout.label(text="Select SCP")
            return

        self._draw_identity(layout, scp)
        self._draw_transform(layout, scp)
        self._draw_mirror(layout, scp)
        self._draw_shape_params(layout, scp)
        self._draw_constraints_header(layout, scp)
        for i, c in enumerate(scp.constraints):
            self._draw_constraint_item(layout, scp, i, c)
        layout.operator("af.delete_selected_af_node", icon="TRASH")
