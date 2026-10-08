"""Create an explicit relationship even when automatic broad filtering found no pair."""
import json
import bpy
from ..core.utils import get_af_root
from ..core.muscle_pairs import runtime
from ..core.muscle_relationships import service

STRINGS = {}
ITEMS = []


def domains(_owner, context):
    if context is None: return ITEMS
    root = get_af_root(context.scene)
    if root is None: return []
    try: values, _ = service.inputs((context.scene, root))
    except ValueError: return []
    names = {m.id: m.name for m in root.af_vcp_system.muscles}; result = []
    for d in values:
        key = json.dumps([d.key.muscle, d.key.instance, d.key.side])
        label = f'{names.get(d.key.muscle, d.key.muscle)} · {d.key.instance} · {d.key.side}'
        result.append(tuple(STRINGS.setdefault(s, s) for s in (key, label, 'Current native inflation side')))
    ITEMS[:] = result
    return ITEMS


class AF_OT_explicit_order(bpy.types.Operator):
    bl_idname = 'af.muscle_explicit_order'
    bl_label = 'Assign underlying and covering muscle'
    bl_options = {'UNDO'}
    underlying: bpy.props.EnumProperty(name='Underlying', items=domains)
    covering: bpy.props.EnumProperty(name='Covering', items=domains)

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=480)

    def draw(self, context):
        self.layout.prop(self, 'underlying'); self.layout.prop(self, 'covering')
        self.layout.label(text='Explicit order allows crossing bases; attachments remain fixed.')

    def execute(self, context):
        root = get_af_root(context.scene); scope = context.scene, root
        try:
            state = runtime.inspect(*scope); pair = [json.loads(self.underlying), json.loads(self.covering)]
            change = dict(relationships=[dict(pair=pair, cover=pair[1], mode='explicit')])
            service.configure(scope, change, state['relationship_revision'])
        except (ValueError, RuntimeError, KeyError) as error:
            self.report({'ERROR'}, str(error)); return {'CANCELLED'}
        return {'FINISHED'}


def register():
    bpy.utils.register_class(AF_OT_explicit_order)


def unregister():
    bpy.utils.unregister_class(AF_OT_explicit_order); ITEMS.clear(); STRINGS.clear()
