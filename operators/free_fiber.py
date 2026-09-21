"""One native editor operator with explicit, undoable actions."""
import bpy
from ..app.queries.root import root_for_context
from ..adapters import free_fiber_editor as editor


def _object_mode(context):
    if context.object is not None and context.object.mode != 'OBJECT': bpy.ops.object.mode_set(mode='OBJECT')


def _enter_edit(context, objects):
    _object_mode(context)
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects: obj.hide_set(False); obj.select_set(True)
    if objects:
        context.view_layer.objects.active = objects[0]; bpy.ops.object.mode_set(mode='EDIT')


def _run(context, root, fiber, action):
    _object_mode(context)
    if action == 'EDIT': return _enter_edit(context, editor.open_edit(root, context.scene, fiber))
    if action == 'APPLY': return editor.apply(root, context.scene, fiber)
    if action == 'CANCEL': return editor.cancel(root, fiber)
    if action in {'REFRESH', 'REBASE'}: return _enter_edit(context, editor.refresh(root, context.scene, fiber, action == 'REBASE'))
    if action == 'BEZIER': editor.convert_bezier(root, fiber)
    if action == 'RESAMPLE': editor.resample(root, fiber)
    return _enter_edit(context, editor.objects(editor.state(root, fiber)))


class AF_OT_FreeFiberPath(bpy.types.Operator):
    bl_idname = 'af.free_fiber_path'
    bl_label = 'Free Fiber Path'
    bl_options = {'REGISTER', 'UNDO'}
    fiber_id: bpy.props.StringProperty()
    action: bpy.props.EnumProperty(items=[(key, key.title(), '') for key in ('EDIT', 'APPLY', 'CANCEL', 'REFRESH', 'REBASE', 'BEZIER', 'RESAMPLE')])

    def execute(self, context):
        root = root_for_context(context)
        fiber = next((f for f in root.af_vcp_system.fibers if f.id == self.fiber_id), None) if root else None
        if fiber is None: self.report({'ERROR'}, 'Fiber not found.'); return {'CANCELLED'}
        try: _run(context, root, fiber, self.action)
        except (ValueError, RuntimeError) as error:
            self.report({'ERROR'}, str(error)); return {'CANCELLED'}
        return {'FINISHED'}


def register():
    from ..adapters import free_fiber_lifecycle
    bpy.utils.register_class(AF_OT_FreeFiberPath); free_fiber_lifecycle.register()


def unregister():
    from ..adapters import free_fiber_lifecycle
    free_fiber_lifecycle.unregister(); bpy.utils.unregister_class(AF_OT_FreeFiberPath)
