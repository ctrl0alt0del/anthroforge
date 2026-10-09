"""Explicit support and shared-point attachment controls."""
import bpy
from ..app.queries.root import root_for_context
from ..app.use_cases import fiber_attachment as service
from ..core.vcp.attachment_surface import resolve_object

_TARGET_ITEMS = []
_CHOICE_CACHE = {}


def _target_items(operator, context):
    from ..app.queries.fiber_attachment import surface_choices
    global _TARGET_ITEMS
    if context is not None:
        rows = tuple(surface_choices(root_for_context(context), context.scene))
        _TARGET_ITEMS = _CHOICE_CACHE.setdefault(rows, rows)
    return _TARGET_ITEMS


def _invoke(operator, context):
    if operator.action not in {'ADD', 'ASSIGN'}: return operator.execute(context)
    items = _target_items(operator, context)
    if not items: operator.report({'ERROR'}, 'No attachment surfaces are available.'); return {'CANCELLED'}
    choices = {row[0] for row in items}
    operator.surface_choice = operator.target_id if operator.target_id in choices else items[0][0]
    operator.use_choice = True
    return context.window_manager.invoke_props_dialog(operator, width=480)


class AF_OT_FiberAttachment(bpy.types.Operator):
    bl_idname = 'af.fiber_attachment'
    bl_label = 'Edit Fiber Attachment'
    bl_options = {'REGISTER', 'UNDO'}
    action: bpy.props.EnumProperty(items=[(v, v.title(), '') for v in ('ADD', 'REMOVE', 'SELECT', 'ASSIGN', 'REBIND', 'REBIND_ALL')])
    fiber_id: bpy.props.StringProperty()
    point_id: bpy.props.StringProperty()
    target_id: bpy.props.StringProperty()
    surface_choice: bpy.props.EnumProperty(name='Surface', items=_target_items)
    use_choice: bpy.props.BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        return _invoke(self, context)

    def draw(self, context):
        self.layout.prop(self, 'surface_choice')
        if self.action == 'ASSIGN': self.layout.label(text='The 3D cursor specifies the attachment position.')

    def execute(self, context):
        root = root_for_context(context)
        if root is None: return {'CANCELLED'}
        try: _execute(self, context, root)
        except (ValueError, RuntimeError) as error:
            self.report({'ERROR'}, str(error)); return {'CANCELLED'}
        return {'FINISHED'}


def _execute(operator, context, root):
    if operator.action == 'SELECT': return _select(context, root, operator.target_id)
    if operator.action in {'ASSIGN', 'REBIND'}: return _point(operator, context, root)
    fiber = next((f for f in root.af_vcp_system.fibers if f.id == operator.fiber_id), None)
    if fiber is None: raise ValueError('Fiber is unavailable.')
    if operator.action == 'REBIND_ALL': return service.rebind_fiber(root, context.scene, fiber)
    targets = [row.target_id for row in fiber.attachment_supports]
    if operator.action == 'ADD': targets.append(_target(operator, context, root))
    else: targets = [value for value in targets if value != operator.target_id]
    service.set_supports(root, context.scene, fiber, targets)


def _point(operator, context, root):
    point = next((p for p in root.af_vcp_system.authored_points if p.id == operator.point_id), None)
    if point is None: raise ValueError('Shared point is unavailable.')
    if operator.action == 'REBIND': return service.rebind(root, context.scene, point, context.scene.cursor.location)
    target = _target(operator, context, root)
    return service.assign(root, context.scene, point, target, context.scene.cursor.location)


def _target(operator, context, root):
    return operator.surface_choice if operator.use_choice else service.selected_target(root, context.active_object)


def _select(context, root, target):
    from ..core.visualization.surface_target_service import default_surface_target_service
    from ..core.vcp.surface_reference import reference
    result = default_surface_target_service().resolve(root, context.scene, reference(target))
    obj = result.mesh_object if result else None
    if obj is None: raise ValueError('Surface is unavailable.')
    for selected in context.selected_objects: selected.select_set(False)
    obj.hide_set(False); obj.select_set(True); context.view_layer.objects.active = obj


class AF_OT_FiberAttachmentSymmetry(bpy.types.Operator):
    bl_idname = 'af.fiber_attachment_symmetry'
    bl_label = 'Fiber Attachment Symmetry'
    bl_options = {'REGISTER', 'UNDO'}
    fiber_id: bpy.props.StringProperty()
    mode: bpy.props.EnumProperty(items=[('INHERIT', 'Inherit', ''), ('NONE', 'Independent', ''), ('EXPLICIT', 'Explicit Plane', '')])
    axis: bpy.props.EnumProperty(items=[(v, v, '') for v in ('X', 'Y', 'Z')])
    origin: bpy.props.FloatVectorProperty(size=3, subtype='TRANSLATION')

    def invoke(self, context, event):
        root = root_for_context(context)
        fiber = next((f for f in root.af_vcp_system.fibers if f.id == self.fiber_id), None) if root else None
        if fiber is None: return {'CANCELLED'}
        self.mode = {'explicit': 'NONE', 'native_mirror': 'EXPLICIT'}.get(fiber.get('af_authoring_symmetry'), 'INHERIT')
        self.axis = fiber.get('af_authoring_mirror_axis', 'X')
        self.origin = fiber.get('af_authoring_mirror_origin', (0., 0., 0.))
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, 'mode')
        if self.mode == 'EXPLICIT':
            self.layout.prop(self, 'axis'); self.layout.prop(self, 'origin')

    def execute(self, context):
        root = root_for_context(context)
        fiber = next((f for f in root.af_vcp_system.fibers if f.id == self.fiber_id), None) if root else None
        if fiber is None: return {'CANCELLED'}
        try: service.set_symmetry(root, context.scene, fiber, self.mode, self.axis, self.origin)
        except (ValueError, RuntimeError) as error:
            self.report({'ERROR'}, str(error)); return {'CANCELLED'}
        return {'FINISHED'}
