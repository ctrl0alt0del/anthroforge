"""Native branch editing, sharing the application operations used by authoring."""
import bpy
from ..app.queries.root import root_for_context
from ..app.queries.vcp import active_muscle_from_context, active_fiber_from_context
from ..app.use_cases import muscle_branch as use
from ..core.vcp.shared_point_storage import slots, ensure_point, point_users, point_record


class AF_OT_AddMuscleBranch(bpy.types.Operator):
    bl_idname = "af.add_muscle_branch"
    bl_label = "Add Fiber Loft Branch"
    bl_options = {'REGISTER', 'UNDO'}
    branch_surface: bpy.props.StringProperty(name="Branch Surface ID")
    boundary_fiber: bpy.props.StringProperty(name="Main Boundary Fiber ID")
    root_indices: bpy.props.StringProperty(name="Ordered Main Point Indices", default="1,2")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=430)

    def draw(self, context):
        self.layout.prop(self, 'branch_surface')
        self.layout.prop(self, 'boundary_fiber')
        self.layout.prop(self, 'root_indices')
        self.layout.label(text="One main midpoint per branch fiber, in loft order.")
        self.layout.label(text="Branch start endpoints will share these points.")

    def execute(self, context):
        try:
            root, muscle = root_for_context(context), active_muscle_from_context(context)
            fiber = next(f for f in root.af_vcp_system.fibers if f.id == self.boundary_fiber)
            references = slots(fiber)
            ids = [ensure_point(*references[int(i)][:2]).id for i in self.root_indices.split(',')]
            use.add_branch(root, muscle.id, self.branch_surface, fiber.id, ids)
            return {'FINISHED'}
        except (ValueError, StopIteration, IndexError, AttributeError) as error:
            self.report({'ERROR'}, str(error) or "Invalid muscle, surface or fiber")
            return {'CANCELLED'}


class AF_OT_RemoveMuscleBranch(bpy.types.Operator):
    bl_idname = "af.remove_muscle_branch"
    bl_label = "Remove Branch Connection"
    bl_options = {'REGISTER', 'UNDO'}
    connection_id: bpy.props.StringProperty()

    def execute(self, context):
        use.remove_branch(root_for_context(context), active_muscle_from_context(context).id, self.connection_id)
        return {'FINISHED'}


class AF_OT_DetachSharedPoint(bpy.types.Operator):
    bl_idname = "af.detach_shared_point"
    bl_label = "Detach This Point Use"
    bl_options = {'REGISTER', 'UNDO'}
    fiber_id: bpy.props.StringProperty()
    index: bpy.props.IntProperty(min=0)

    def execute(self, context):
        try:
            use.detach_point(root_for_context(context), self.fiber_id, self.index)
            return {'FINISHED'}
        except (ValueError, IndexError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


class AF_OT_SelectMusclePart(bpy.types.Operator):
    bl_idname = 'af.select_muscle_part'
    bl_label = 'Edit Loft Inflation'
    bl_options = {'REGISTER', 'UNDO'}
    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        root, muscle = root_for_context(context), active_muscle_from_context(context)
        surface = use.muscle_surface(root, muscle)
        if self.index < -1 or self.index >= len(surface.branches):
            return {'CANCELLED'}
        surface.active_branch_index = self.index
        use._dirty(root, muscle, set())
        return {'FINISHED'}


def draw_branches(panel, context):
    muscle = active_muscle_from_context(context)
    if muscle is None or muscle.surface_source_mode != "FIBER_SURFACE":
        return
    root = root_for_context(context)
    surface = use.muscle_surface(root, muscle)
    panel.layout.operator('af.add_muscle_branch', icon='ADD')
    if surface.branches:
        panel.layout.operator('af.select_muscle_part', text='Edit Main Inflation').index = -1
    for index, connection in enumerate(surface.branches):
        _draw_connection(panel.layout, connection, index)


def _draw_connection(layout, connection, index):
    box = layout.box()
    box.label(text="Branch: " + connection.surface_id)
    row = box.row(); row.prop(connection, 'width'); row.prop(connection, 'fullness')
    box.operator('af.select_muscle_part', text='Edit Branch Inflation').index = index
    box.operator('af.remove_muscle_branch', icon='X').connection_id = connection.id


def draw_points(panel, context):
    fiber, root = active_fiber_from_context(context), root_for_context(context)
    if fiber is None:
        return
    box = panel.layout.box(); box.label(text="Authored Points and Shared Uses")
    for index, (owner, slot, role) in enumerate(slots(fiber)):
        point = point_record(owner, slot)
        if point is None:
            continue
        row = box.row(); row.label(text=f"{index}: {role}")
        row.enabled = False; row.prop(owner, slot, text="ID")
        users = point_users(root, point.id)
        box.label(text=", ".join(f"{f.id}[{i}]" for f, i, _ in users))
        if len(users) > 1:
            op = box.operator('af.detach_shared_point'); op.fiber_id, op.index = fiber.id, index


CLASSES = (AF_OT_AddMuscleBranch, AF_OT_RemoveMuscleBranch, AF_OT_DetachSharedPoint, AF_OT_SelectMusclePart)


def register():
    from .panels.vcp_edit_panel import AF_PT_VCPEditPanel
    from .panels.fiber_edit_panel import AF_PT_FiberEditPanel
    for cls in CLASSES:
        if not cls.is_registered:
            bpy.utils.register_class(cls)
    AF_PT_VCPEditPanel.remove(draw_branches)
    AF_PT_FiberEditPanel.remove(draw_points)
    AF_PT_VCPEditPanel.append(draw_branches)
    AF_PT_FiberEditPanel.append(draw_points)


def unregister():
    from .panels.vcp_edit_panel import AF_PT_VCPEditPanel
    from .panels.fiber_edit_panel import AF_PT_FiberEditPanel
    AF_PT_VCPEditPanel.remove(draw_branches)
    AF_PT_FiberEditPanel.remove(draw_points)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
